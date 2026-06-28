# email_plugin - 邮箱插件

为 Bot 提供邮箱收发的能力。支持通过 IMAP 接收邮件并将其转化为 Bot 的消息流，同时支持通过 SMTP 发送回复。

## 功能特性

- **邮箱收信**：基于 IMAP 协议定时轮询收取未读邮件，转化为内部消息传递给 Bot 进行处理。
- **邮件状态管理**：引入三态管理机制（`PENDING` / `READ` / `REPLIED`）使用框架提供的 JSON 存储 API 进行持久化，防止邮件被重复投递或处理。
- **邮箱发信**：基于 SMTP 协议，允许 Bot 通过调用特定动作（如 `reply_email`）直接向指定邮箱发送邮件回复。
- **主流邮箱支持**：支持 QQ 邮箱、163 邮箱、Gmail、Outlook 等主流邮箱服务的连接配置（需获取第三方授权码）。
- **会话上下文保持**：在发信时传入原邮件的 `Message-ID` 作为 `In-Reply-To` 和 `References` 请求头，使接收方可以完美聚合邮件对话线。

## 安装方式

将本插件目录复制或克隆至 Neo-MoFox 项目的 `plugins/email_plugin` 下：

```bash
git clone https://github.com/tt-P607/email_plugin.git plugins/email_plugin
```

## 配置指南

插件首次运行后会在主配置目录自动生成：`config/plugins/email_plugin/config.toml`。请在其中填写您的邮箱凭证：

```toml
[account]
imap_server = "imap.qq.com"
imap_port = 993
smtp_server = "smtp.qq.com"
smtp_port = 465
email_address = "your_bot_email@qq.com"
password = "your_auth_code" # 注意：QQ/163/Gmail 均需使用“授权码”，而非邮箱登录密码
use_ssl = true

[polling]
enabled = true
interval_seconds = 60 # 轮询收取新邮件的时间间隔（秒）

[chatter]
bot_email_display_name = "Bot" # 发送邮件回复时显示的发件人昵称
```

## 动作与工具说明

### Actions (动作组件)

- `reply_email`：SMTP 回复邮件。
  - `to_email`: 收件人邮箱地址。
  - `subject`: 邮件主题。
  - `content`: 邮件正文。
  - `reply_to_msg_id`: (可选) 被回复邮件的 Message-ID，用于邮件聚合。
- `mark_email_read`：将本地邮件状态更新为 `READ` 或 `REPLIED`。

### Tools (工具组件)

- `check_email`：检查 Bot 收件箱的邮件状态（支持按 `PENDING` 等条件筛选）。
- `search_email`：在本地收到的邮件库中搜索历史邮件。

## 技术规范

- 开发语言：Python 3.11+
- 外部依赖：无额外重型第三方库，使用内置的 `email`、`imaplib`、`smtplib` 库实现
- 数据存储：使用框架提供的 JSON 存储接口（`storage_api`）进行持久化
