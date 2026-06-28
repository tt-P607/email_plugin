"""邮箱 Tool 组件：主动检查和搜索邮件，以及查看可用附件。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, cast

from src.core.components.base.tool import BaseTool
from src.app.plugin_system.api.service_api import get_service

if TYPE_CHECKING:
    from .service import EmailService

# 附件文件存放目录
ATTACHMENTS_DIR = Path("data/email_plugin/test_attachments")


class CheckEmailTool(BaseTool):
    """主动检查收件箱最新邮件。"""

    tool_name = "check_email"
    tool_description = "主动检查邮箱中是否有最新收到的未读/未处理邮件"

    async def execute(
        self,
        limit: Annotated[int, "一次最多检查的新邮件数量，默认5"] = 5,
    ) -> tuple[bool, str | list[dict[str, Any]]]:
        """执行邮件检查。"""
        plugin_name = self.plugin.plugin_name if self.plugin else "email_plugin"
        service = get_service(f"{plugin_name}:service:email_service")

        if not service:
            return False, "内部错误：找不到 email_service"

        email_service = cast("EmailService", service)

        try:
            mails = await email_service.fetch_new_emails(limit=limit)
            if not mails:
                return True, "收件箱目前没有未处理的新邮件。"

            result = []
            for mail in mails:
                result.append({
                    "id": mail.message_id,
                    "sender": f"{mail.sender_name} <{mail.sender}>",
                    "subject": mail.subject,
                    "date": mail.date_str,
                    "snippet": mail.body[:200] + "..." if len(mail.body) > 200 else mail.body,
                })

            return True, result

        except Exception as e:
            return False, f"检查邮件失败：{e}"


class SearchEmailTool(BaseTool):
    """搜索邮箱中往期已处理或历史邮件。"""

    tool_name = "search_email"
    tool_description = "搜索本地已归档的往期邮件历史，可以通过主题、发件人等关键词检索"

    async def execute(
        self,
        keyword: Annotated[str, "搜索关键词，可以为空"],
        limit: Annotated[int, "最多返回的结果数，默认10"] = 10,
    ) -> tuple[bool, str | list[dict[str, Any]]]:
        """执行邮件搜索。"""
        plugin_name = self.plugin.plugin_name if self.plugin else "email_plugin"
        service = get_service(f"{plugin_name}:service:email_service")

        if not service:
            return False, "内部错误：找不到 email_service"

        email_service = cast("EmailService", service)

        try:
            history = await email_service.search_emails(query=keyword, limit=limit)
            if not history:
                return True, "未检索到匹配的历史邮件"

            result = []
            for mail in history:
                result.append({
                    "id": mail.message_id,
                    "sender": f"{mail.sender_name} <{mail.sender}>",
                    "subject": mail.subject,
                    "date": mail.date_str,
                    "snippet": mail.body[:200] + "..." if len(mail.body) > 200 else mail.body,
                })
            return True, result
        except Exception as e:
            return False, f"检索历史邮件失败：{e}"


class ListAttachmentsTool(BaseTool):
    """查看附件目录中可用的文件。

    注意：此 Tool 已实现但暂未注册到插件组件列表（plugin.py get_components），
    附件功能入口待后续设计后启用。启用时在 plugin.py 和 manifest.json 中注册即可。
    附件文件存放目录：data/email_plugin/test_attachments/
    """

    tool_name = "list_attachments"
    tool_description = "查看附件目录中可用的文件列表，用于发送带附件的邮件时选择文件"

    async def execute(self) -> tuple[bool, str | list[dict[str, Any]]]:
        """列出附件目录中的所有文件。"""
        if not ATTACHMENTS_DIR.exists():
            return True, "附件目录不存在，暂无可用附件"

        files: list[dict[str, Any]] = []
        for entry in sorted(ATTACHMENTS_DIR.iterdir()):
            if entry.is_file():
                stat = entry.stat()
                files.append({
                    "filename": entry.name,
                    "size": stat.st_size,
                    "path": str(entry),
                })

        if not files:
            return True, "附件目录为空，暂无可用附件"

        return True, files
