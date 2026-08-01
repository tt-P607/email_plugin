"""邮箱插件注册入口。"""

from src.app.plugin_system.base import BasePlugin, register_plugin
from src.app.plugin_system.api.log_api import get_logger

from .config import EmailPluginConfig
from .components.service import EmailService
from .components.adapter import EmailAdapter
from .components.chatter import EmailChatter
from .components.actions import ReplyEmailAction, MarkEmailReadAction
from .components.tools import CheckEmailTool, SearchEmailTool

logger = get_logger("email_plugin", display="邮箱插件")


@register_plugin
class EmailPlugin(BasePlugin):
    """邮箱插件，为 Bot 提供邮箱收发的能力。"""

    plugin_name = "email_plugin"

    config: EmailPluginConfig
    configs = [EmailPluginConfig]

    async def on_plugin_loaded(self) -> None:
        """插件加载时注册提示词模板。"""
        from .prompts import register_email_prompts

        register_email_prompts()
        logger.info("邮箱插件提示词模板已注册")

    def get_components(self) -> list[type]:
        """返回邮箱收发、会话与管理组件。"""
        return [
            EmailService,
            EmailAdapter,
            EmailChatter,
            ReplyEmailAction,
            MarkEmailReadAction,
            CheckEmailTool,
            SearchEmailTool,
        ]
