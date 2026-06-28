"""本地邮件留档与状态管理。

使用框架公开的 storage_api (save_json/load_json) 实现往期邮件历史、
已处理记录的索引和检索，以及三态管理（PENDING/READ/REPLIED）。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from src.app.plugin_system.api import storage_api
from src.app.plugin_system.api.log_api import get_logger
from .mail_client import MailMessage

logger = get_logger("email_plugin.mail_tracker", display="邮件存储索引")

STORE_NAME = "email_plugin"
MAILS_KEY = "archived_emails"
STATUS_KEY = "email_status"


class EmailStatus(str, Enum):
    """邮件处理状态。"""

    PENDING = "pending"    # 已投递到核心流，等待 bot 处理
    READ = "read"          # bot 已查看/处理
    REPLIED = "replied"    # bot 已回复


class MailTracker:
    """邮件历史及状态追踪器。"""

    def __init__(self) -> None:
        pass

    # ── 状态管理 ──

    async def _load_status_map(self) -> dict[str, str]:
        """加载邮件状态映射。"""
        try:
            data = await storage_api.load_json(STORE_NAME, STATUS_KEY)
            if isinstance(data, dict) and "map" in data and isinstance(data["map"], dict):
                return data["map"]
        except Exception as e:
            logger.warning(f"加载邮件状态记录失败(可能文件为空或损坏)，当作空数据处理: {e}")
        return {}

    async def _save_status_map(self, status_map: dict[str, str]) -> None:
        """保存邮件状态映射（只保留最近 1000 条）。"""
        if len(status_map) > 1000:
            # 保留最新的 1000 条
            keys = list(status_map.keys())[-1000:]
            status_map = {k: status_map[k] for k in keys}
        await storage_api.save_json(STORE_NAME, STATUS_KEY, {"map": status_map})

    async def get_status(self, message_id: str) -> EmailStatus | None:
        """获取邮件状态。"""
        status_map = await self._load_status_map()
        raw = status_map.get(message_id)
        if raw is None:
            return None
        try:
            return EmailStatus(raw)
        except ValueError:
            return None

    async def set_status(self, message_id: str, status: EmailStatus) -> None:
        """设置邮件状态。"""
        status_map = await self._load_status_map()
        status_map[message_id] = status.value
        await self._save_status_map(status_map)

    async def set_status_batch(self, message_ids: list[str], status: EmailStatus) -> None:
        """批量设置邮件状态。"""
        if not message_ids:
            return
        status_map = await self._load_status_map()
        for mid in message_ids:
            status_map[mid] = status.value
        await self._save_status_map(status_map)

    async def get_known_ids(self) -> set[str]:
        """获取所有已知状态的邮件 ID 集合（PENDING/READ/REPLIED 都算）。"""
        status_map = await self._load_status_map()
        return set(status_map.keys())

    # ── 归档管理 ──

    async def archive_mail(self, mail: MailMessage) -> None:
        """归档一封邮件。"""
        try:
            data = await storage_api.load_json(STORE_NAME, MAILS_KEY)
        except Exception as e:
            logger.warning(f"加载归档邮件记录失败(可能文件为空或损坏)，当作空数据处理: {e}")
            data = None
            
        mails_list: list[dict[str, Any]] = []
        if isinstance(data, dict) and "list" in data and isinstance(data["list"], list):
            mails_list = data["list"]

        # 检查是否已有同 ID 邮件
        for m in mails_list:
            if m.get("message_id") == mail.message_id:
                return

        mails_list.append(mail.to_dict())
        # 最多归档 500 封往期邮件
        if len(mails_list) > 500:
            mails_list = mails_list[-500:]

        await storage_api.save_json(STORE_NAME, MAILS_KEY, {"list": mails_list})

    async def get_all_archived(self) -> list[MailMessage]:
        """获取所有已归档邮件。"""
        try:
            data = await storage_api.load_json(STORE_NAME, MAILS_KEY)
        except Exception as e:
            logger.warning(f"加载归档邮件记录失败(可能文件为空或损坏)，当作空数据处理: {e}")
            data = None
            
        if isinstance(data, dict) and "list" in data and isinstance(data["list"], list):
            return [MailMessage.from_dict(item) for item in data["list"]]
        return []

    async def get_archived_mail(self, message_id: str) -> MailMessage | None:
        """根据 Message-ID 查找归档邮件。"""
        all_mails = await self.get_all_archived()
        for mail in all_mails:
            if mail.message_id == message_id:
                return mail
        return None

    async def search_emails(self, query: str, limit: int = 10) -> list[MailMessage]:
        """按主题、发件人或正文关键词搜索邮件。"""
        all_mails = await self.get_all_archived()
        if not query.strip():
            return list(reversed(all_mails))[:limit]

        query_lower = query.lower()
        matched: list[MailMessage] = []
        for mail in reversed(all_mails):
            if (
                query_lower in mail.subject.lower()
                or query_lower in mail.sender.lower()
                or query_lower in mail.sender_name.lower()
                or query_lower in mail.body.lower()
            ):
                matched.append(mail)
                if len(matched) >= limit:
                    break
        return matched
