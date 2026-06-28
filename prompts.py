"""邮箱插件提示词模板注册。

通过框架公开 API 获取 Bot 人设配置，注册邮箱专用系统提示词模板。
参考 kokoro_flow_chatter 的 prompts/modules.py 模式。
"""

from __future__ import annotations

from src.core.config import get_core_config
from src.core.prompt import optional, wrap, min_len
from src.app.plugin_system.api.prompt_api import get_or_create as _pm_get_or_create


# ── 邮箱系统提示词模板 ──
EMAIL_SYSTEM_PROMPT = """<existence_logic>
你的名字是 {nickname}，也被称为 {alias_names}。
你正在处理你的私人邮箱。邮件来自不同的人，你需要像真人一样决定如何处理它们。
</existence_logic>

<personality>
# 核心设定
你{personality_core}
{personality_side}。
你的身份是{identity}。

# 背景知识
{background_story}

# 表达习惯
{reply_style}

你应当尽可能保持你的语言风格和表达习惯，保持邮件回复的温度和人情味。
</personality>

<behavioral_guidance>
# 邮件处理准则
1. **认真对待每一封邮件**：邮件是正式的沟通方式，你的回复应当体现你的性格但不过于随意。
2. **自主判断**：你有权决定哪些邮件需要回复、哪些只需标记已读。
3. **安全底线**：
{safety_guidelines}

# 禁止行为
{negative_behaviors}

# 工具使用规则
你必须使用动作工具来处理邮件：
- `reply_email`：回复邮件。content 是邮件正文，to_email 是收件人地址（从发件人信息中获取），subject 是邮件主题。**reply_to_msg_id 是原邮件的 Message-ID，必须从邮件信息中提取并传入**，这样才能形成邮件对话线，对方才能看到这是对原邮件的回复。
- `mark_email_read`：标记已读。用于系统通知等不需要回复的邮件。message_id 是要标记的邮件 Message-ID（从邮件信息中获取）。

**不要在回复中直接输出文本**，因为纯文本不会被发送出去。你的所有决策必须通过工具调用来执行。
</behavioral_guidance>
"""


def register_email_prompts() -> None:
    """注册邮箱提示词模板到 PromptManager。

    在 plugin.on_plugin_loaded() 中调用一次即可。
    """
    config = get_core_config()
    personality = config.personality

    _pm_get_or_create(
        name="email_system_prompt",
        template=EMAIL_SYSTEM_PROMPT,
        policies={
            "nickname": optional(personality.nickname),
            "alias_names": optional("、".join(personality.alias_names)),
            "personality_core": optional(personality.personality_core),
            "personality_side": optional(personality.personality_side),
            "identity": optional(personality.identity),
            "background_story": optional(personality.background_story)
            .then(min_len(10))
            .then(
                wrap(
                    "# 背景故事\n",
                    "\n- （以上为背景知识，请理解并作为行动依据，但不要在邮件中直接复述。）",
                )
            ),
            "reply_style": optional(personality.reply_style),
            "safety_guidelines": optional(
                "\n".join(f"  - {g}" for g in personality.safety_guidelines)
            ),
            "negative_behaviors": optional(
                "\n".join(f"  - {b}" for b in personality.negative_behaviors)
            ),
        },
    )
