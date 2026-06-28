"""邮箱插件的配置定义。

配置文件默认路径：config/plugins/email_plugin/config.toml
支持 QQ邮箱、Gmail、163邮箱、Outlook 等主流邮箱服务。
"""

from __future__ import annotations

from typing import ClassVar
from src.app.plugin_system.base import BaseConfig, Field, SectionBase, config_section


class EmailPluginConfig(BaseConfig):
    """邮箱插件的配置结构。"""

    config_name: ClassVar[str] = "config"
    config_description: ClassVar[str] = "邮箱插件收发与轮询配置"

    @config_section("account")
    class AccountSection(SectionBase):
        """邮件账户连接与身份凭证配置。

        支持 QQ邮箱、Gmail、163邮箱、Outlook 等。
        大多数邮箱需要授权码而非登录密码，获取方式：
        - QQ邮箱：https://service.mail.qq.com/detail/0/75
        - Gmail：https://myaccount.google.com/apppasswords
        - 163邮箱：https://mail.163.com → 设置 → POP3/SMTP/IMAP
        - Outlook：可直接使用登录密码
        """

        imap_server: str = Field(
            default="imap.qq.com",
            description="IMAP 服务器地址（QQ: imap.qq.com, Gmail: imap.gmail.com, 163: imap.163.com, Outlook: outlook.office365.com）",
        )
        imap_port: int = Field(
            default=993,
            description="IMAP SSL 端口",
        )
        smtp_server: str = Field(
            default="smtp.qq.com",
            description="SMTP 服务器地址（QQ: smtp.qq.com, Gmail: smtp.gmail.com, 163: smtp.163.com, Outlook: smtp.office365.com）",
        )
        smtp_port: int = Field(
            default=465,
            description="SMTP 端口（SSL 常用 465，STARTTLS 常用 587）",
        )
        email_address: str = Field(
            default="",
            description="Bot 邮箱地址",
        )
        password: str = Field(
            default="",
            description="Bot 邮箱授权码（不是登录密码）。QQ邮箱获取：https://service.mail.qq.com/detail/0/75 ，Gmail获取：https://myaccount.google.com/apppasswords ，163邮箱：网页版设置中开启IMAP后获取",
        )
        use_ssl: bool = Field(
            default=True,
            description="是否启用 SSL 安全连接",
        )

    @config_section("polling")
    class PollingSection(SectionBase):
        """收取邮件轮询配置。"""

        enabled: bool = Field(
            default=True,
            description="是否启用后台邮件自动轮询收取",
        )
        interval_seconds: int = Field(
            default=60,
            description="收信轮询时间间隔（秒），最小支持 10 秒",
        )

    @config_section("chatter")
    class ChatterSection(SectionBase):
        """邮箱 Chatter 人设设置。"""

        bot_email_display_name: str = Field(
            default="小狐狸",
            description="回复发信时发件人的昵称",
        )

    account: AccountSection = Field(default_factory=AccountSection)
    polling: PollingSection = Field(default_factory=PollingSection)
    chatter: ChatterSection = Field(default_factory=ChatterSection)
