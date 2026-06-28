"""邮箱入站适配器。

轮询 IMAP 收件箱，获取未处理的最新邮件，转换为 MessageEnvelope
并投递给 CoreSink 核心接收器（private 类型的私人邮箱流）。
投递成功后立即标记为 PENDING 状态，防止下一轮轮询重复投递。
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, cast

from mofox_wire import CoreSink, MessageEnvelope
from mofox_wire.types import UserRole

from src.app.plugin_system.base import BaseAdapter
from src.app.plugin_system.api.log_api import get_logger, COLOR
from src.app.plugin_system.api.service_api import get_service
from src.kernel.concurrency import get_task_manager

from ..config import EmailPluginConfig

if TYPE_CHECKING:
    from .service import EmailService

logger = get_logger("email_plugin.adapter", color=COLOR.CYAN)


class EmailAdapter(BaseAdapter):
    """邮箱入站适配器组件。"""

    adapter_name = "email_adapter"
    adapter_version = "2.0.0"
    adapter_description = "邮箱 IMAP 轮询入站适配器"
    platform = "email"

    def __init__(self, core_sink: CoreSink, plugin: Any | None, **kwargs: Any) -> None:
        super().__init__(core_sink, plugin, **kwargs)
        self._poll_task_id: str | None = None

    @property
    def _cfg(self) -> EmailPluginConfig | None:
        """类型安全的配置访问。"""
        if self.plugin is None:
            return None
        config = self.plugin.config
        if isinstance(config, EmailPluginConfig):
            return config
        return None

    async def on_adapter_loaded(self) -> None:
        """适配器加载时启动邮件轮询任务。"""
        cfg = self._cfg
        if cfg is None:
            logger.error("EmailAdapter 加载失败：插件配置不可用")
            return

        if not cfg.polling.enabled:
            logger.info("邮件轮询功能已禁用，不启动轮询协程。")
            return

        tm = get_task_manager()
        task_info = tm.create_task(
            self._poll_loop(),
            name="email_plugin_imap_poll",
            daemon=True,
        )
        self._poll_task_id = task_info.task_id
        logger.info(f"邮件轮询任务启动，轮询间隔: {cfg.polling.interval_seconds} 秒")

    async def on_adapter_unloaded(self) -> None:
        """适配器卸载时取消轮询。"""
        if self._poll_task_id:
            tm = get_task_manager()
            try:
                tm.cancel_task(self._poll_task_id)
                logger.info("已停止邮件轮询任务")
            except Exception as e:
                logger.error(f"停止邮件轮询任务失败: {e}")
            self._poll_task_id = None

    async def health_check(self) -> bool:
        """因为是无常驻轮询适配器，健康检查直接返回 True。"""
        return True

    async def _poll_loop(self) -> None:
        """邮件轮询主循环。"""
        # 首次立即执行一次，不等待 interval
        first_run = True
        while True:
            cfg = self._cfg
            if cfg is None or not cfg.polling.enabled:
                break

            interval = max(10, cfg.polling.interval_seconds)
            try:
                if not first_run:
                    await asyncio.sleep(interval)
                first_run = False
                await self._check_and_dispatch_emails()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"邮件轮询发生未捕获异常: {e}")
                # 异常后等待 interval 再重试，避免疯狂重试
                await asyncio.sleep(interval)

    async def _check_and_dispatch_emails(self) -> None:
        """拉取新邮件并分发到核心，投递后立即标记 PENDING 防止重复。"""
        try:
            plugin_name = self.plugin.plugin_name if self.plugin else "email_plugin"
            service = get_service(f"{plugin_name}:service:email_service")
            if not service:
                logger.warning("未找到 email_service 服务组件，跳过本轮轮询")
                return

            email_service = cast("EmailService", service)

            new_mails = await email_service.fetch_new_emails(limit=5)
            if not new_mails:
                return

            logger.info(f"检测到 {len(new_mails)} 封未读/未处理邮件，开始投递到核心流...")
            dispatched_ids: list[str] = []
            for mail in new_mails:
                # 使用 private 类型：邮箱是 bot 的私人空间
                # user_id 使用发件人邮箱地址
                envelope: MessageEnvelope = {
                    "direction": "incoming",
                    "message_info": {
                        "platform": self.platform,
                        "message_id": mail.message_id,
                        "time": time.time(),
                        "user_info": {
                            "platform": self.platform,
                            "user_id": mail.sender,
                            "user_nickname": mail.sender_name,
                            "role": UserRole.MEMBER,
                        },
                    },
                    "message_segment": [
                        {
                            "type": "text",
                            "data": (
                                f"【邮件ID】: {mail.message_id}\n"
                                f"【发件人】: {mail.sender_name} <{mail.sender}>\n"
                                f"【主题】: {mail.subject}\n"
                                f"【正文】:\n{mail.body}"
                            ),
                        }
                    ],
                    "raw_message": mail.to_dict(),
                }
                await self.core_sink.send(envelope)  # type: ignore[arg-type]
                dispatched_ids.append(mail.message_id)

            # 投递成功后立即标记为 PENDING
            if dispatched_ids:
                await email_service.mark_pending(dispatched_ids)
                logger.debug(f"已标记 {len(dispatched_ids)} 封邮件为 PENDING")

        except Exception as e:
            logger.error(f"轮询并分发邮件出错: {e}")

    async def from_platform_message(self, raw: Any) -> MessageEnvelope:
        """适配器只在主动轮询时自建 Envelope，此方法不需要具体实现。"""
        raise NotImplementedError(
            "EmailAdapter utilizes poll loop and does not parse raw server push messages."
        )

    async def _send_platform_message(self, envelope: MessageEnvelope) -> None:
        """发送平台消息。

        邮件的真正发送动作由 reply_email Action 通过 EmailService 完成，
        不走 Adapter 管道，因此这里为空实现。
        """
        pass

    async def get_bot_info(self) -> dict[str, Any]:
        """获取 Bot 邮箱标识信息。"""
        cfg = self._cfg
        email_addr = cfg.account.email_address if cfg else "unknown@email.com"
        display_name = cfg.chatter.bot_email_display_name if cfg else "邮箱服务"
        return {
            "bot_id": email_addr,
            "bot_name": display_name,
            "platform": self.platform,
        }
