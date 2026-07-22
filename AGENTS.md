# AGENTS.md

## 项目概览

这是一个独立的 MaiBot Tool 插件，为模型提供 QQ 的 `send_poke`（戳一戳）能力。戳一戳是一种比直接 `@` 或点名更含蓄的提醒和互动方式，模型可以根据普通聊天语境自主决定是否使用。

插件本身不直接连接 QQ，也不实现协议适配，而是依赖 SnowLuma Adapter 公开的
`adapter.napcat.message.send_poke` 插件 API。当前仅支持 **SnowLuma + SnowLuma Adapter** 链路，暂不支持 MaiBot 的 NapCat Adapter 或其他适配器。

模型只会看到一个可选参数 `msg_id`：

- 提供 `msg_id` 时，目标是当前 QQ 会话中该普通消息的发送者。
- 省略 `msg_id` 时，插件会尝试从当前会话最近的消息中找到刚刚发给机器人的 SnowLuma 戳一戳通知，用于处理“用户只戳了机器人、没有发送普通消息”的情况。

本插件不会监听戳一戳事件、缓存用户、自动触发戳一戳或修改 MaiBot、SnowLuma、SnowLuma Adapter。所有实际操作都必须由模型调用 Tool 后发生。

## 当前关键契约

- 插件 ID：`github.happycola233.maibot-poke-plugin`
- 显示名：`MaiBot 戳一戳插件`
- LLM Tool：`send_poke`
- Tool 必须保持 `visibility="visible"`。
- Tool 只向模型公开可选的 `msg_id`，不要公开 `stream_id`、`user_id`、`group_id` 等会扩大调用范围的参数。
- `stream_id`、`chat_id`、`platform`、`user_id` 和 `group_id` 由 MaiBot Host 按当前对话注入。
- 所有消息查询必须限定在当前 `stream_id`，并拒绝跨会话或非 QQ 消息。
- 显式 `msg_id` 只能指向普通用户消息，不能把通知消息 ID 当作普通目标使用。
- 省略 `msg_id` 时，只查询当前会话最近 20 条消息；只接受 120 秒内、处于最新时间点、目标为机器人且能唯一确定发起者的 SnowLuma `notify.poke` 通知。
- 回退取得内部通知 ID 后，必须再通过 `message.get_by_id` 复核会话、平台和通知身份；内部通知 ID 不得返回给模型。
- 群聊调用底层 API 时传 `user_id` 和 `group_id`；私聊只传 `user_id`。
- Host 调用成功不等于 QQ 操作成功；只有 SnowLuma 返回 `status="ok"` 且 `retcode` 为整数 `0` 才能报告成功。
- 所有失败都应返回模型能理解的明确中文信息，不能静默成功。

## 仓库结构

- `plugin.py`：插件配置模型、Tool 声明、目标解析、安全校验和 Adapter API 调用。
- `_manifest.json`：插件身份、版本范围、依赖和 capabilities。
- `README.md`：面向用户的安装、配置、使用边界、兼容性和故障排查说明。
- `tests/test_plugin.py`：配置、Manifest、Tool Schema、群聊/私聊、回退流程和错误路径的回归测试。
- `config.toml`：由 MaiBot 根据配置模型生成，是本地运行配置，不提交仓库。

当前配置模型保持最小化，只提供启用开关和隐藏的 `config_version`。SnowLuma 连接、目标选择和会话信息都不应在本插件中重复配置。

## 权威资料与参考实现

参考仓库：

- `C:\Users\admin\Documents\GitHub\MaiBot`
- `C:\Users\admin\Documents\GitHub\SnowLuma`
- `C:\Users\admin\Documents\GitHub\Mai-with-u_MaiBot-SnowLuma-Adapter`

这些仓库默认只读，用于核对真实数据结构、能力签名、调用链和兼容范围。除非用户明确授权，不得修改它们。

严格参考 MaiBot 插件开发文档：

- https://github.com/Mai-with-u/plugin-repo/blob/main/CONTRIBUTING.md
- https://docs.mai-mai.org/plugin/
- https://docs.mai-mai.org/plugin/vibe-coding

不要依赖记忆或旧示例推断当前 API。开始涉及 SDK、Manifest、配置、Tool、消息结构或上架规则的工作前，先打开上述资料并积极搜索互联网中的最新官方文档与上游源码。优先使用官方文档、官方仓库和实际代码；发现文档与代码不一致时，明确指出版本与证据，不要自行猜测。

## 开发原则

- 深度思考，积极搜索互联网查询最新开发文档，包括但不限于上述链接。
- 选择最小、清晰、可验证的实现，避免屎山、回归、代码冗余和过度兜底。
- 在关键边界和不直观的判断处写简洁中文注释

## 安全边界

- 不接受模型直接指定 QQ 号或群号，目标身份只能来自当前会话中经过校验的消息。
- 不依赖最近消息列表的返回顺序，应按时间戳判断最新消息；同一最新时间点存在不同发起者时必须拒绝猜测。
- 较新的普通消息或非目标通知出现后，不得继续复用更早的戳一戳通知。
- 最近通知筛选完成后仍要执行 `get_by_id`，避免绕过普通路径已有的会话、平台、群聊和私聊检查。
- 不把 SnowLuma 的 Host 调用结果与业务结果混为一谈，也不要把布尔值 `False` 当作合法的整数 `0`。
- MaiBot 当前对 Tool 隐藏上下文字段的注入来源存在上游可信边界：插件无法独立证明同名参数一定来自 Host。如果任务要求形式上彻底防止模型覆盖这些字段，应先说明需要上游修复，不得用重复比较伪装成已解决，也不得未经授权修改 MaiBot。

## 验证要求

必须兼顾 Manifest 声明的最低 SDK 版本和当前 SDK 版本；现阶段至少在 `maibot-plugin-sdk` 2.7.0 与 2.7.1 下运行测试。不要只因导入成功就声称功能完成，也不要在没有真实环境验证时声称已经完成 QQ 端到端测试。

## 文档、版本与 Git

- 用户要求 Conventional Commit 时，使用通俗易懂的中文，标题描述整个工作区的实际成果；不要把与用户的对话迭代写成提交历史。
