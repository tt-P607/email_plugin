"""Email 聊天器组件 v4。

自己实现核心对话循环，不依赖任何外部插件源码。
通过 ``prompt_api`` 获取注册的 ``email_system_prompt`` 模板（含完整人设），
使用 ``BaseChatter`` 提供的 ``create_request`` / ``inject_usables`` /
``run_tool_call`` 完成工具调用闭环。

多轮对话使用框架标准 API ``LLMResponse.send()``，自动处理上下文管理。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncGenerator

from src.core.components.base.chatter import (
    BaseChatter,
    ChatterResult,
    Failure,
    Success,
    WaitResumeEvent,
)
from src.core.components.types import ChatType
from src.app.plugin_system.api.log_api import get_logger, COLOR

if TYPE_CHECKING:
    from src.core.models.message import Message
    from src.core.models.stream import ChatStream
    from src.kernel.llm import LLMResponse

logger = get_logger("email_plugin.chatter", display="邮件聊天器", color=COLOR.CYAN)

# 最大工具调用轮数，防止死循环
_MAX_TOOL_ROUNDS = 5


class EmailChatter(BaseChatter):
    """EmailChatter 邮箱回复决策聊天器 v4。

    邮件流使用 private 类型，所有投递的邮件都会走自己实现的核心逻辑。
    通过 ``prompt_api`` 获取注册的系统提示词模板（含完整人设），
    保证与主 chatter 人设一致。
    """

    chatter_name = "email_chatter"
    chatter_description = "邮箱回复与拟人思考组件"
    associated_platforms = ["email"]
    chat_type = ChatType.PRIVATE
    dependencies = [
        "email_plugin:service:email_service",
    ]

    def _print_decision_panel(self, chat_stream: ChatStream, response: LLMResponse) -> None:
        """打印 LLM 决策面板，显示思考、独白和工具调用。"""
        thought = (
            response.reasoning_content.strip()
            if response.reasoning_content
            else "（无）"
        )
        monologue = response.message.strip() if response.message else "（无）"

        tool_lines: list[str] = []
        for call in response.call_list or []:
            args: dict[str, Any] = call.args if isinstance(call.args, dict) else {}
            formatted = ", ".join(f"{k}={v}" for k, v in args.items()) if args else ""
            if formatted:
                tool_lines.append(f"    {call.name} ({formatted})")
            else:
                tool_lines.append(f"    {call.name}")

        tools_text = "\n".join(tool_lines) if tool_lines else "    （无）"
        panel_content = (
            f"聊天流：{chat_stream.stream_id[:8]}...\n\n"
            f"思考：{thought}\n\n"
            f"独白：{monologue}\n\n"
            f"调用工具：\n{tools_text}"
        )
        logger.print_panel(
            panel_content,
            title="邮件处理决策",
            border_style="cyan",
        )

    async def _build_system_prompt(self, chat_stream: ChatStream) -> str:
        """构建系统提示词，从 PromptManager 获取注册的模板并渲染。"""
        from src.app.plugin_system.api.prompt_api import get_template

        tmpl = get_template("email_system_prompt")
        if tmpl is None:
            logger.warning("email_system_prompt 模板未注册，使用兜底提示词")
            return (
                f"你是 {chat_stream.bot_nickname}，正在处理私人邮箱。"
                "请使用 reply_email 或 mark_email_read 动作处理邮件。"
            )
        return await tmpl.build()

    async def _build_user_prompt(self, unreads_text: str) -> str:
        """构建用户提示词，将未读邮件内容传入。"""
        return (
            f"你收到了以下新邮件：\n\n{unreads_text}\n\n"
            "请决定如何处理这些邮件（必须使用动作工具）。"
        )

    async def execute(
        self,
    ) -> AsyncGenerator[ChatterResult, WaitResumeEvent | None]:
        """独立实现的邮件对话循环。"""

        from src.core.managers.stream_manager import get_stream_manager
        from src.kernel.llm import LLMPayload, ROLE, Text

        # ── 1. 激活聊天流 ──
        stream_manager = get_stream_manager()
        chat_stream = await stream_manager.activate_stream(self.stream_id)
        if chat_stream is None:
            logger.error(f"无法激活聊天流: {self.stream_id}")
            yield Failure("无法激活聊天流")
            return

        self.apply_stream_runtime_options(chat_stream)

        # ── 2. 读取并格式化未读消息 ──
        unreads_text, unread_msgs = await self.fetch_unreads()
        if not unread_msgs:
            yield Success("没有新邮件，结束轮次")
            return

        # trigger_msg 是最后一条未读消息，run_tool_call 需要它来恢复发送上下文
        trigger_msg: Message | None = unread_msgs[-1] if unread_msgs else None

        # ── 3. 构建请求 ──
        sys_prompt = await self._build_system_prompt(chat_stream)
        user_prompt = await self._build_user_prompt(unreads_text)

        request = self.create_request()
        request.add_payload(LLMPayload(ROLE.SYSTEM, Text(sys_prompt)))
        request.add_payload(LLMPayload(ROLE.USER, Text(user_prompt)))

        # 注入可用动作/工具
        registry = await self.inject_usables(request)
        if not registry.get_all():
            logger.warning("没有可用的邮箱动作，结束处理。")
            await self.flush_unreads(unread_msgs)
            yield Failure("没有可用的邮箱动作")
            return

        # ── 4. 对话循环（LLM 调用 → 工具执行 → 再调用…） ──
        try:
            response: LLMResponse | None = None
            round_count = 0

            while round_count < _MAX_TOOL_ROUNDS:
                round_count += 1
                logger.info(f"邮件处理第 {round_count} 轮 LLM 请求...")

                if response is None:
                    # 首轮：从 request 发送
                    response = await request.send(stream=False)
                else:
                    # 后续轮：从 response.send() 继续对话
                    # send() 自动消费当前响应、追加 assistant payload、创建新请求、保留 context_manager
                    response = await response.send(stream=False)

                # 消费响应以将 assistant payload 追加到上下文，
                # 这样 run_tool_call 追加 TOOL_RESULT 时不会出现孤立的 tool_result
                if not response._consumed:
                    await response

                # 打印决策面板
                self._print_decision_panel(chat_stream, response)

                # 非流式模式下 call_list 已填充
                call_list = response.call_list or []
                if not call_list:
                    if round_count == 1:
                        logger.warning(
                            "LLM 未调用任何动作，可能忽略了这些邮件。"
                        )
                    break

                # 执行工具调用，结果自动写回 response 的 TOOL_RESULT payload
                await self.run_tool_call(
                    calls=call_list,
                    response=response,
                    usable_map=registry,
                    trigger_msg=trigger_msg,
                )
                # response.send() 会在下一轮自动处理 payload 追加和上下文裁剪

            else:
                logger.warning(
                    f"邮件处理达到最大轮数 {_MAX_TOOL_ROUNDS}，强制结束。"
                )

        except Exception as e:
            logger.error(f"邮件处理 LLM 调用失败: {e}", exc_info=True)
            yield Failure(f"LLM 调用失败: {e}")
            return

        finally:
            # ── 5. 清理未读消息 ──
            await self.flush_unreads(unread_msgs)

        yield Success("邮件处理轮次完成")
