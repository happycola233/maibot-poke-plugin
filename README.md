# MaiBot 戳一戳插件

为 MaiBot 提供模型可调用的 QQ 戳一戳工具。插件依赖 SnowLuma Adapter，将其公开的
`adapter.napcat.message.send_poke` API 注册为可见 LLM Tool `send_poke`。

> [!IMPORTANT]
> 本插件目前仅支持通过 SnowLuma 与 SnowLuma Adapter 使用，暂不支持 MaiBot 的 NapCat Adapter。

模型可以根据普通群聊或私聊的语境，自主决定是否戳某条消息的发送者；也可以在用户只戳机器人、没有发送
普通消息时，尝试戳回该用户。目标用户不需要先戳机器人。

## 功能边界

- Tool 只向模型公开一个必填但可为 `null` 的参数 `msg_id`：传非空字符串时定位普通消息发送者，传 `null` 时尝试定位刚刚戳机器人的用户。
- `stream_id` 由 MaiBot Host 按当前对话自动注入，不暴露给模型填写。
- `msg_id=null` 时只查询当前会话最近 20 条消息，并且只接受 120 秒内、位于最新时间点、唯一且目标为机器人的
  SnowLuma QQ 戳一戳通知。
- 确定内部通知 ID 后仍通过 `message.get_by_id` 进入与普通消息相同的会话、平台和身份校验流程。
- 群聊向 Adapter 传递 `user_id` 和 `group_id`；私聊只传递 `user_id`。
- 分别检查 Host 调用结果与 SnowLuma 的 `status`、`retcode`，向模型返回明确的中文结果。
- 不监听戳一戳事件，不缓存用户，不自动触发，也不修改 MaiBot、SnowLuma 或 SnowLuma Adapter。

## 运行要求

- MaiBot Host `>=1.0.6,<=2.0.0`
- `maibot-plugin-sdk >=2.7.0,<3.0.0`
- SnowLuma Adapter `>=0.8.4,<1.0.0`
- SnowLuma Adapter 已正确连接 SnowLuma

这些范围也写在根目录的 `_manifest.json` 中，由 MaiBot Host 在加载前校验。本插件仅提供标准启用元配置，
不提供戳一戳业务参数。

## 安装

将仓库克隆到 MaiBot 的 `plugins` 目录：

```shell
cd /path/to/MaiBot/plugins
git clone https://github.com/happycola233/maibot-poke-plugin.git
```

同时安装并启用依赖插件 `maibot-team.snowluma-adapter`。重启 MaiBot 或在插件管理页重新加载插件后，
确认 `github.happycola233.maibot-poke-plugin` 已启用。

## 配置

Runner 会根据最小配置模型在安装目录生成 `config.toml`：

```toml
[plugin]
enabled = true
config_version = "1.0.0"
```

WebUI 只向用户展示插件启用开关；`config_version` 为隐藏、只读的配置版本字段。目标用户和当前会话由每次 Tool
调用确定，SnowLuma 的连接信息由 SnowLuma Adapter 管理，因此本插件不重复提供相关设置。

## Tool 契约

Tool 名称：`send_poke`

参数：

```json
{
  "msg_id": "目标用户在当前 QQ 会话中发送的消息 ID"
}
```

或：

```json
{
  "msg_id": null
}
```

每次调用都必须提供 `msg_id`，其值可以是非空字符串或 `null`：

- 填 `msg_id`：戳这条消息的发送者，适用于普通群聊或私聊。它必须是当前会话中某条用户普通消息真实、非空的 ID。
- 传 `msg_id=null`：戳回刚戳过机器人的人，仅当最新消息都是戳向机器人的 SnowLuma QQ 戳一戳通知、且能唯一锁定同一个人时才生效。
- 空字符串、纯空白或随手填的内容都不是合法 `msg_id`，也不等于 `null`；传 `null` 不会自动挑最近的普通消息。
- 回退时用到的内部通知 ID 不会返回给模型，也不能反过来当作 `msg_id`。

`send_poke` 设置为 `visibility="visible"`，因此模型在普通聊天中可以直接看到并自主选择该工具。调用会产生真实的
QQ 互动；工具描述会提醒模型只在语境合适时使用。

## 聊天命令

本插件不提供聊天命令，所有行为都由模型通过 `send_poke` Tool 自主决定。

## 安全与结果判定

执行流程如下：

1. 要求 Host 注入的 `stream_id`、`chat_id` 非空且完全一致，并确认当前平台为 `qq`。
2. `msg_id` 是非空字符串时，直接调用 `message.get_by_id(msg_id, stream_id=当前会话)`，并拒绝将通知消息 ID 当作普通消息使用。
3. `msg_id=null` 时，调用 `message.get_recent(当前会话, limit=20)`，自行按时间戳确定最新时间点；通知必须在
   120 秒内，且该时间点必须能唯一确定一位戳一戳发起者。
4. 回退通知必须同时满足：同一 `session_id`、QQ 平台、`is_notify=true`、SnowLuma `notify.poke`、
   `target_id=self_id`，并且通知中包含有效、非机器人自身的发送者 `user_id`。
5. 取得通知的内部合成 ID 后，再通过 `message.get_by_id` 复核会话、平台和通知身份；回退结果不向模型返回该 ID。
6. 从 `message_info.user_info.user_id` 取得目标；群聊再从 `group_info.group_id` 取得群号。群聊要求群号与当前
   上下文一致；私聊要求发送者就是当前私聊对象。
7. 通过 Host 调用完整 API 名
   `maibot-team.snowluma-adapter.adapter.napcat.message.send_poke`。
8. 只有 SnowLuma 同时返回 `status="ok"` 和整数 `retcode=0` 才视为成功。

API 未找到、Adapter 未连接、RPC 超时、跨会话消息、非 QQ 消息、畸形消息数据以及 SnowLuma 业务失败，都会作为
`success=false` 的结构化结果返回模型，不会静默成功。

## 测试

安装开发所需 SDK 后运行标准库单元测试：

```shell
python -m pip install "maibot-plugin-sdk>=2.7.0,<3.0.0"
python -m unittest discover -s tests -v
```

单元测试覆盖最小配置 Schema、Tool 可见性、参数 Schema、空会话保护、Host 两层失败、跨会话/非 QQ 拒绝、
群聊与私聊参数差异、最近通知回退、通知过期与同秒歧义拒绝，以及 SnowLuma `status` / `retcode` 的严格判定。
发布前仍建议在真实 QQ 群聊和私聊各完成一次端到端测试。

## Manifest 能力

插件只申请实际使用的 Host capabilities：

- `message.get_by_id`
- `message.get_recent`
- `api.call`

Manifest 使用 v2，`plugin_type` 为 `tool`，并显式依赖 `maibot-team.snowluma-adapter`。

开发规范参考：

- [MaiBot 插件开发文档](https://docs.mai-mai.org/plugin/)
- [MaiBot Vibe Coding 指南](https://docs.mai-mai.org/plugin/vibe-coding)
- [MaiBot Tool 组件文档](https://docs.mai-mai.org/plugin/tools)
- [MaiBot Manifest 文档](https://docs.mai-mai.org/plugin/manifest)
- [MaiBot 插件中心贡献指南](https://github.com/Mai-with-u/plugin-repo/blob/main/CONTRIBUTING.md)

## 常见问题与故障排查

### 用户刚戳了机器人，为什么仍然没有戳回？

请确认 SnowLuma Adapter 已启用通知传递和戳一戳通知。为避免戳错人，以下情况会明确拒绝回退：通知超过 120 秒、
通知之后又出现了更新消息、最新时间点包含非戳通知或多位发起者、被戳目标不是机器人，或通知字段不完整。此时
如果该用户在当前会话中有普通消息，模型仍可使用其 `msg_id` 调用工具。

### 为什么不让模型直接填写 QQ 号？

模型通常只能看到昵称，直接开放 `user_id` 会扩大为可指定任意 QQ 用户的能力。插件只从当前会话中的真实消息或
经过严格筛选的戳一戳通知提取目标。

## 开源许可

本项目基于 [MIT License](LICENSE) 开源，可自由使用、修改与分发。
