"""底层邮件收发客户端。

封装基于 Python 内置库 imaplib, smtplib 和 email 的异步/线程池操作，
不引入外部第三方大依赖。
"""

from __future__ import annotations

import asyncio
from email.header import decode_header
from email.message import EmailMessage
import email.parser
import email.policy
from email.utils import make_msgid, parseaddr
import imaplib
import os
import smtplib
from typing import Any

from src.app.plugin_system.api.log_api import get_logger

logger = get_logger("email_plugin.mail_client", display="邮件客户端")


class MailMessage:
    """邮件结构化实体。"""

    def __init__(
        self,
        message_id: str,
        subject: str,
        sender: str,
        sender_name: str,
        recipient: str,
        body: str,
        date_str: str,
        attachments: list[dict[str, Any]] | None = None,
        references: str = "",
    ) -> None:
        self.message_id = message_id
        self.subject = subject
        self.sender = sender
        self.sender_name = sender_name
        self.recipient = recipient
        self.body = body
        self.date_str = date_str
        self.attachments = attachments or []
        # 原始邮件的 References header（对话链历史，空格分隔的 Message-ID 列表）
        self.references = references

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "message_id": self.message_id,
            "subject": self.subject,
            "sender": self.sender,
            "sender_name": self.sender_name,
            "recipient": self.recipient,
            "body": self.body,
            "date_str": self.date_str,
            "attachments": self.attachments,
            "references": self.references,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MailMessage:
        """从字典还原。"""
        return cls(
            message_id=data.get("message_id", ""),
            subject=data.get("subject", ""),
            sender=data.get("sender", ""),
            sender_name=data.get("sender_name", ""),
            recipient=data.get("recipient", ""),
            body=data.get("body", ""),
            date_str=data.get("date_str", ""),
            attachments=data.get("attachments", []),
            references=data.get("references", ""),
        )


def _decode_str(header_value: Any) -> str:
    """解码邮件标题或名字。"""
    if not header_value:
        return ""
    try:
        decoded = decode_header(header_value)
        parts = []
        for content, charset in decoded:
            if isinstance(content, bytes):
                try:
                    parts.append(content.decode(charset or "utf-8", errors="replace"))
                except Exception:
                    parts.append(content.decode("gbk", errors="replace"))
            else:
                parts.append(str(content))
        return "".join(parts)
    except Exception:
        return str(header_value)


def _parse_email_bytes(raw_bytes: bytes) -> MailMessage:
    """同步解析原始邮件字节。"""
    msg = email.message_from_bytes(raw_bytes)

    subject = _decode_str(msg.get("Subject", "无主题"))

    # 解析发件人
    from_header = msg.get("From", "")
    sender_name, sender_addr = parseaddr(from_header)
    sender_name = _decode_str(sender_name)

    # 解析收件人
    to_header = msg.get("To", "")
    _, recipient = parseaddr(to_header)

    # Message-ID 唯一标识
    message_id = msg.get("Message-ID", "")
    if not message_id:
        message_id = make_msgid()

    date_str = msg.get("Date", "")

    # References header（对话链历史）
    references = msg.get("References", "")

    body = ""
    attachments: list[dict[str, Any]] = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))

            # 是否是附件
            if "attachment" in content_disposition or part.get_filename():
                filename = _decode_str(part.get_filename())
                payload = part.get_payload(decode=True)
                if filename and payload:
                    attachments.append({
                        "filename": filename,
                        "content_type": content_type,
                        "size": len(payload),
                        # 暂时不将二进制持久化在 json 里，只记录名字与长度，实际文件可落盘
                    })
            elif content_type == "text/plain" and "attachment" not in content_disposition:
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        body += payload.decode(charset, errors="replace")
                    except Exception:
                        body += payload.decode("gbk", errors="replace")
            elif content_type == "text/html" and "attachment" not in content_disposition and not body:
                # 若无 text/plain 则优先尝试获取 html 正文
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        body += payload.decode(charset, errors="replace")
                    except Exception:
                        body += payload.decode("gbk", errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if isinstance(payload, bytes):
            charset = msg.get_content_charset() or "utf-8"
            try:
                body = payload.decode(charset, errors="replace")
            except Exception:
                body = payload.decode("gbk", errors="replace")

    return MailMessage(
        message_id=str(message_id),
        subject=subject,
        sender=sender_addr,
        sender_name=sender_name,
        recipient=recipient,
        body=body.strip(),
        date_str=date_str,
        attachments=attachments,
        references=str(references),
    )


class MailClient:
    """邮件收发同步库包装的异步 MailClient。"""

    def __init__(
        self,
        imap_server: str,
        imap_port: int,
        smtp_server: str,
        smtp_port: int,
        email_address: str,
        password: str,
        use_ssl: bool = True,
    ) -> None:
        self.imap_server = imap_server
        self.imap_port = imap_port
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.email_address = email_address
        self.password = password
        self.use_ssl = use_ssl

    def _sync_fetch_latest_emails(self, limit: int = 5) -> list[MailMessage]:
        """同步获取最新邮件。"""
        if not self.email_address or not self.password:
            logger.warning("未配置邮箱账户或密码，跳过收信操作")
            return []

        mail: imaplib.IMAP4 | None = None
        try:
            if self.use_ssl:
                mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            else:
                mail = imaplib.IMAP4(self.imap_server, self.imap_port)

            mail.login(self.email_address, self.password)
            mail.select("INBOX")

            # 搜索所有邮件
            status, messages = mail.search(None, "ALL")
            if status != "OK":
                return []

            mail_ids = messages[0].split()
            if not mail_ids:
                return []

            # 只取最新的 limit 封邮件
            target_ids = mail_ids[-limit:]
            results: list[MailMessage] = []

            for m_id in reversed(target_ids):
                res, data = mail.fetch(m_id, "(RFC822)")
                if res != "OK":
                    continue
                raw_email = data[0][1]  # type: ignore
                if isinstance(raw_email, bytes):
                    mail_msg = _parse_email_bytes(raw_email)
                    results.append(mail_msg)

            return results
        except Exception as e:
            logger.error(f"IMAP 收取信件失败: {e}")
            return []
        finally:
            if mail is not None:
                try:
                    mail.close()
                    mail.logout()
                except Exception:
                    pass

    async def fetch_latest_emails(self, limit: int = 5) -> list[MailMessage]:
        """异步拉取最新邮件。"""
        return await asyncio.to_thread(self._sync_fetch_latest_emails, limit)

    def _sync_send_email(
        self,
        to_address: str,
        subject: str,
        body_text: str,
        attachments: list[dict[str, Any]] | None = None,
        reply_to_msg_id: str | None = None,
        references: str = "",
    ) -> bool:
        """同步发送邮件。"""
        if not self.email_address or not self.password:
            logger.warning("未配置邮箱账户或密码，拒绝发送邮件")
            return False

        server: smtplib.SMTP | None = None
        try:
            msg = EmailMessage(policy=email.policy.SMTP)
            msg["Subject"] = subject
            msg["From"] = self.email_address
            msg["To"] = to_address
            msg.set_content(body_text)

            # 设置回复关联 header 达成邮件对话线聚合
            if reply_to_msg_id:
                # 确保 Message-ID 格式正确（RFC 5322 要求 <msgid> 格式）
                msg_id = reply_to_msg_id.strip()
                if not msg_id.startswith("<"):
                    msg_id = f"<{msg_id}>"
                msg["In-Reply-To"] = msg_id

                # 构建 References：原邮件的 References + 原邮件的 Message-ID
                # 这样保留了完整对话链历史
                ref_parts: list[str] = []
                if references:
                    ref_parts.extend(references.split())
                ref_parts.append(msg_id)
                # 去重保持顺序
                seen: set[str] = set()
                unique_refs: list[str] = []
                for r in ref_parts:
                    if r not in seen:
                        seen.add(r)
                        unique_refs.append(r)
                msg["References"] = " ".join(unique_refs)
                logger.info(f"设置回复关联: In-Reply-To={msg_id}, References={' '.join(unique_refs)}")

            if attachments:
                for att in attachments:
                    file_path = att.get("file_path")
                    filename = att.get("filename")
                    content_type = att.get("content_type", "application/octet-stream")

                    if file_path and os.path.exists(file_path):
                        with open(file_path, "rb") as f:
                            file_data = f.read()

                        maintype, subtype = content_type.split("/", 1) if "/" in content_type else ("application", "octet-stream")
                        msg.add_attachment(
                            file_data,
                            maintype=maintype,
                            subtype=subtype,
                            filename=filename or os.path.basename(file_path),
                        )
                    elif att.get("data") and isinstance(att["data"], bytes):
                        # 直接内存二进制
                        file_data = att["data"]
                        maintype, subtype = content_type.split("/", 1) if "/" in content_type else ("application", "octet-stream")
                        msg.add_attachment(
                            file_data,
                            maintype=maintype,
                            subtype=subtype,
                            filename=filename or "attachment",
                        )

            # 通过 SMTP 发送
            if self.use_ssl:
                server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port)
            else:
                server = smtplib.SMTP(self.smtp_server, self.smtp_port)

            server.login(self.email_address, self.password)
            # 打印完整 header 用于调试
            logger.info(f"发送邮件 header: In-Reply-To={msg.get('In-Reply-To', '无')}, References={msg.get('References', '无')}")
            server.send_message(msg)
            logger.info(f"邮件成功发送至 {to_address}，主题: {subject}")
            return True
        except Exception as e:
            logger.error(f"SMTP 发送邮件失败: {e}")
            return False
        finally:
            if server is not None:
                try:
                    server.quit()
                except Exception:
                    pass

    async def send_email(
        self,
        to_address: str,
        subject: str,
        body_text: str,
        attachments: list[dict[str, Any]] | None = None,
        reply_to_msg_id: str | None = None,
        references: str = "",
    ) -> bool:
        """异步发送邮件。"""
        return await asyncio.to_thread(
            self._sync_send_email,
            to_address,
            subject,
            body_text,
            attachments,
            reply_to_msg_id,
            references,
        )
