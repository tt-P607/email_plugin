"""邮箱服务核心组件。

提供给外部插件或内部组件直接调用，封装底层收发逻辑，
实现带本地留档和三态管理（PENDING/READ/REPLIED）的最终接口。
"""

from __future__ import annotations

import datetime
from typing import Any

from src.core.components.base.service import BaseService
from src.app.plugin_system.api.log_api import get_logger
from ..core.mail_client import MailClient, MailMessage
from ..core.mail_tracker import EmailStatus, MailTracker
from ..config import EmailPluginConfig

logger = get_logger("email_plugin.service", display="邮件服务")


class EmailService(BaseService):
    """邮箱业务服务组件。"""

    service_name = "email_service"
    service_description = "提供邮箱收发及三态管理、存储归档的主服务接口"
    version = "2.0.0"

    def __init__(self, plugin: Any) -> None:
        super().__init__(plugin)
        self.tracker = MailTracker()
        self._client: MailClient | None = None

    def _get_client(self) -> MailClient:
        """从插件配置动态构造或返回 Client。"""
        if self._client is not None:
            return self._client

        config = self.plugin.config
        if not isinstance(config, EmailPluginConfig):
            raise ValueError("Plugin config is not type of EmailPluginConfig")
        self._client = MailClient(
            imap_server=config.account.imap_server,
            imap_port=config.account.imap_port,
            smtp_server=config.account.smtp_server,
            smtp_port=config.account.smtp_port,
            email_address=config.account.email_address,
            password=config.account.password,
            use_ssl=config.account.use_ssl,
        )
        return self._client

    async def fetch_new_emails(self, limit: int = 5) -> list[MailMessage]:
        """拉取并筛选出尚未进入系统的最新邮件（不在 PENDING/READ/REPLIED 中）。

        不修改任何状态——由调用方（adapter）在投递后标记为 PENDING。
        """
        client = self._get_client()
        latest_mails = await client.fetch_latest_emails(limit)
        known_ids = await self.tracker.get_known_ids()

        new_mails: list[MailMessage] = []
        for mail in latest_mails:
            if mail.message_id not in known_ids:
                # 归档留档（但不改状态）
                await self.tracker.archive_mail(mail)
                new_mails.append(mail)

        return new_mails

    async def mark_pending(self, message_ids: list[str]) -> None:
        """批量标记邮件为 PENDING（已投递但未处理）。"""
        await self.tracker.set_status_batch(message_ids, EmailStatus.PENDING)

    async def mark_read(self, message_ids: list[str]) -> None:
        """批量标记邮件为 READ（已查看/处理）。"""
        await self.tracker.set_status_batch(message_ids, EmailStatus.READ)

    async def mark_replied(self, message_id: str) -> None:
        """标记邮件为 REPLIED（已回复）。"""
        await self.tracker.set_status(message_id, EmailStatus.REPLIED)

    async def send_mail(
        self,
        to_address: str,
        subject: str,
        body_text: str,
        attachments: list[dict[str, Any]] | None = None,
        reply_to_msg_id: str | None = None,
    ) -> bool:
        """主动发送或回复一封邮件，并自动将自己发出的邮件归档存根。"""
        client = self._get_client()

        # 如果是回复邮件，从归档中查找原邮件的 References 以构建完整对话链
        references = ""
        if reply_to_msg_id:
            orig_mail = await self.tracker.get_archived_mail(reply_to_msg_id)
            if orig_mail:
                references = orig_mail.references

        success = await client.send_email(
            to_address=to_address,
            subject=subject,
            body_text=body_text,
            attachments=attachments,
            reply_to_msg_id=reply_to_msg_id,
            references=references,
        )
        if success:
            config = self.plugin.config
            display_name = (
                config.chatter.bot_email_display_name
                if isinstance(config, EmailPluginConfig)
                else "小狐狸"
            )
            sent_mail = MailMessage(
                message_id=f"sent-{datetime.datetime.now().timestamp()}",
                subject=subject,
                sender=client.email_address,
                sender_name=display_name,
                recipient=to_address,
                body=body_text,
                date_str=datetime.datetime.now().strftime(
                    "%a, %d %b %Y %H:%M:%S +0800"
                ),
                attachments=[
                    {"filename": att.get("filename", "file"), "size": 0}
                    for att in (attachments or [])
                ],
            )
            await self.tracker.archive_mail(sent_mail)
            # 如果是回复某封邮件，将原邮件标记为 REPLIED
            if reply_to_msg_id:
                await self.mark_replied(reply_to_msg_id)
        return success

    async def search_emails(self, query: str, limit: int = 10) -> list[MailMessage]:
        """按关键词查询本地留档的往期所有邮件历史。"""
        return await self.tracker.search_emails(query, limit)
