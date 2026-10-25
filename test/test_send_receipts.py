"""邮箱发送回执边界测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from plugins.email_plugin.components.adapter import EmailAdapter
from plugins.email_plugin.components.service import EmailService
from plugins.email_plugin.core.mail_client import MailClient
from src.core.components.types import PlatformSendResult, PlatformSendStatus


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [TimeoutError("timed out"), OSError("connection lost")])
async def test_smtp_transport_uncertainty_is_not_retryable(failure: Exception, monkeypatch: pytest.MonkeyPatch) -> None:
    """发送调用期间断连或超时必须保留为未知结果。"""
    client = MailClient("imap", 993, "smtp", 465, "bot@example.test", "secret")

    class SMTP:
        def login(self, *_args: object) -> None:
            return None

        def send_message(self, _message: object) -> None:
            raise failure

        def quit(self) -> None:
            return None

    monkeypatch.setattr("plugins.email_plugin.core.mail_client.smtplib.SMTP_SSL", lambda *_args: SMTP())
    result = await client.send_email_result("to@example.test", "subject", "body")

    assert result.status is PlatformSendStatus.UNKNOWN
    assert result.error == str(failure)
    assert await client.send_email("to@example.test", "subject", "body") is False


@pytest.mark.asyncio
async def test_smtp_recipient_refusal_is_confirmed_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """SMTP 明确拒收的收件人应报告确定失败。"""
    client = MailClient("imap", 993, "smtp", 465, "bot@example.test", "secret")

    class SMTP:
        def login(self, *_args: object) -> None:
            return None

        def send_message(self, _message: object) -> dict[str, tuple[int, bytes]]:
            return {"to@example.test": (550, b"mailbox unavailable")}

        def quit(self) -> None:
            return None

    monkeypatch.setattr("plugins.email_plugin.core.mail_client.smtplib.SMTP_SSL", lambda *_args: SMTP())

    result = await client.send_email_result("to@example.test", "subject", "body")

    assert result.status is PlatformSendStatus.FAILED
    assert "to@example.test" in (result.error or "")


@pytest.mark.asyncio
async def test_smtp_acceptance_survives_archive_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """本地归档失败不能把 SMTP 已接受的邮件报告成未发送。"""
    plugin = SimpleNamespace(config=SimpleNamespace(chatter=SimpleNamespace(bot_email_display_name="Bot")))
    service = EmailService(plugin=plugin)
    client = SimpleNamespace(
        email_address="bot@example.test",
        send_email_result=AsyncMock(return_value=PlatformSendResult(success=True)),
    )
    service._client = client
    service.tracker.archive_mail = AsyncMock(side_effect=OSError("archive failed"))

    result = await service.send_mail_result("to@example.test", "subject", "body")

    assert result.status is PlatformSendStatus.SENT
    assert result.success is False
    assert "archive failed" in (result.error or "")
    assert "不要重复发送" in (result.error or "")
    assert await service.send_mail("to@example.test", "subject", "body") is True


@pytest.mark.asyncio
async def test_smtp_acceptance_survives_mark_replied_failure() -> None:
    """标记原邮件失败不能覆盖已接受的新邮件发送状态。"""
    plugin = SimpleNamespace(config=SimpleNamespace(chatter=SimpleNamespace(bot_email_display_name="Bot")))
    service = EmailService(plugin=plugin)
    service._client = SimpleNamespace(
        email_address="bot@example.test",
        send_email_result=AsyncMock(return_value=PlatformSendResult(success=True)),
    )
    service.tracker.get_archived_mail = AsyncMock(return_value=None)
    service.tracker.archive_mail = AsyncMock()
    service.mark_replied = AsyncMock(side_effect=OSError("status write failed"))

    result = await service.send_mail_result(
        "to@example.test", "subject", "body", reply_to_msg_id="original-id",
    )

    assert result.status is PlatformSendStatus.SENT
    assert result.success is False
    assert "status write failed" in (result.error or "")
    assert "不要重复发送" in (result.error or "")
    assert await service.send_mail(
        "to@example.test", "subject", "body", reply_to_msg_id="original-id",
    ) is True


@pytest.mark.asyncio
async def test_generic_adapter_outbound_is_explicitly_unsupported() -> None:
    """通用 Envelope 出站必须明确拒绝，不得折叠成未知或成功。"""
    adapter = object.__new__(EmailAdapter)

    result = await adapter._send_platform_message({})

    assert result.status is PlatformSendStatus.FAILED
    assert "不支持通用消息出站" in (result.error or "")
