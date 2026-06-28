"""邮件专用 Action 组件。

提供 ``reply_email`` 和 ``mark_email_read`` 两个邮件专属动作，
只对 ``email_chatter`` 可见。
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, AsyncGenerator, cast

from src.core.components.base.action import BaseAction
from src.app.plugin_system.api.log_api import get_logger, COLOR
from src.app.plugin_system.api.service_api import get_service

if TYPE_CHECKING:
    from .service import EmailService

logger = get_logger("email_plugin.actions", display="邮件动作", color=COLOR.CYAN)

# 附件文件存放目录（与 ListAttachmentsTool 共用）
ATTACHMENTS_DIR = Path("data/email_plugin/test_attachments")


class ReplyEmailAction(BaseAction):
    """回复一封邮件。

    直接通过 SMTP 发送纯文本邮件给指定收件人，支持附带附件。
    """

    action_name = "reply_email"
    action_description = (
        "回复一封邮件。你收到邮件后如果想回复，请使用此动作。"
        "content 是邮件正文内容，to_email 是收件人邮箱地址（从发件人信息中获取），"
        "subject 是邮件主题。"
        "reply_to_msg_id 是原邮件的 Message-ID，必须从邮件信息中提取并传入，"
        "这样才能形成邮件对话线，对方才能看到这是对原邮件的回复。"
    )
    chatter_allow: list[str] = ["email_chatter"]
    associated_types = ["text"]

    async def execute(
        self,
        content: Annotated[str, "邮件正文内容"],
        to_email: Annotated[str, "收件人邮箱地址"],
        subject: Annotated[str, "邮件主题"] = "来自收件箱的回复",
        reply_to_msg_id: Annotated[str, "关联的原始邮件 Message-ID，可选"] = "",
        # 附件功能：参数保留但暂未在 action_description 中暴露给 LLM，
        # 待 ListAttachmentsTool 启用后再开放。附件目录：data/email_plugin/test_attachments/
        attachments: Annotated[str, "附件文件名，多个用逗号分隔（暂未启用）"] = "",
        reason: Annotated[str, "回复理由"] = "",
    ) -> AsyncGenerator[tuple[bool, str], None]:
        """执行邮件发送。"""
        plugin_name = self.plugin.plugin_name if self.plugin else "email_plugin"
        service = get_service(f"{plugin_name}:service:email_service")

        if not service:
            yield False, "内部错误：未找到 email_service"
            return

        email_service = cast("EmailService", service)

        # 解析附件文件名
        attachment_list: list[dict[str, str]] = []
        if attachments:
            filenames = [f.strip() for f in attachments.split(",") if f.strip()]
            for filename in filenames:
                file_path = ATTACHMENTS_DIR / filename
                if file_path.exists() and file_path.is_file():
                    content_type, _ = mimetypes.guess_type(str(file_path))
                    attachment_list.append({
                        "file_path": str(file_path),
                        "filename": filename,
                        "content_type": content_type or "application/octet-stream",
                    })
                    logger.info(f"已加载附件: {filename}")
                else:
                    logger.warning(f"附件文件不存在: {filename}")

        try:
            success = await email_service.send_mail(
                to_address=to_email,
                subject=subject,
                body_text=content,
                reply_to_msg_id=reply_to_msg_id if reply_to_msg_id else None,
                attachments=attachment_list if attachment_list else None,
            )
            if success:
                att_info = f"（含 {len(attachment_list)} 个附件）" if attachment_list else ""
                logger.info(f"已回复邮件给 {to_email}，主题: {subject}{att_info}")
                yield True, f"邮件已成功发送给 {to_email}{att_info}"
            else:
                yield False, f"发送邮件给 {to_email} 失败"
        except Exception as e:
            logger.error(f"回复邮件异常: {e}")
            yield False, f"发送邮件异常: {e}"

    async def go_activate(self) -> bool:
        """邮件回复动作始终激活。"""
        return True


class MarkEmailReadAction(BaseAction):
    """将邮件标记为已读。

    当 bot 查看了邮件但不需要回复时，可以使用此动作标记为已读。
    """

    action_name = "mark_email_read"
    action_description = (
        "将邮件标记为已读。当你看过一封邮件但不需要回复时使用此动作。"
        "message_id 是要标记的邮件 Message-ID（可以从邮件信息中获取）。"
        "可以传入多个用逗号分隔的 ID 来批量标记。"
    )
    chatter_allow: list[str] = ["email_chatter"]
    associated_types = ["text"]

    async def execute(
        self,
        message_id: Annotated[str, "邮件 Message-ID，多个用逗号分隔"],
        reason: Annotated[str, "标记理由"] = "",
    ) -> AsyncGenerator[tuple[bool, str], None]:
        """执行标记已读。"""
        plugin_name = self.plugin.plugin_name if self.plugin else "email_plugin"
        service = get_service(f"{plugin_name}:service:email_service")

        if not service:
            yield False, "内部错误：未找到 email_service"
            return

        email_service = cast("EmailService", service)

        try:
            # 支持逗号分隔的多个 ID
            ids = [mid.strip() for mid in message_id.split(",") if mid.strip()]
            if not ids:
                yield True, "没有需要标记的邮件"
                return

            await email_service.mark_read(ids)
            yield True, f"已标记 {len(ids)} 封邮件为已读"
        except Exception as e:
            logger.error(f"标记邮件已读异常: {e}")
            yield False, f"标记失败: {e}"

    async def go_activate(self) -> bool:
        """标记已读动作始终激活。"""
        return True
