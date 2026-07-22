# MaiBot 戳一戳插件

为 MaiBot 提供模型可调用的 QQ 戳一戳工具。插件依赖 SnowLuma Adapter，将其公开的
`adapter.napcat.message.send_poke` API 注册为可见 LLM Tool `send_poke`。

模型可以根据普通群聊或私聊的语境，自主决定是否戳某条消息的发送者；目标用户不需要先戳机器人。

## 功能边界

- Tool 只接收一个必填参数 `msg_id`，即目标用户发送的消息 ID。
- `stream_id` 由 MaiBot Host 按当前对话自动注入，不暴露给模型填写。
- 消息查询始终带当前 `stream_id`，并交叉校验 Host 注入的 `chat_id`、`platform` 与会话身份字段。
- 群聊向 Adapter 传递 `user_id` 和 `group_id`；私聊只传递 `user_id`。
- 分别检查 Host 调用结果与 SnowLuma 的 `status`、`retcode`，向模型返回明确的中文结果。
- 不监听戳一戳事件，不缓存用户，不自动触发，也不修改 MaiBot、SnowLuma 或 SnowLuma Adapter。

## 运行要求

- MaiBot Host `>=1.0.6,<=1.1.99`
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

`send_poke` 设置为 `visibility="visible"`，因此模型在普通聊天中可以直接看到并自主选择该工具。调用会产生真实的
QQ 互动；工具描述会提醒模型只在语境合适时使用。

## 安全与结果判定

执行流程如下：

1. 拒绝空 `msg_id`，并要求 Host 注入的 `stream_id`、`chat_id` 非空且完全一致，防止消息查询退化为全局查询。
2. 要求 Host 注入的当前平台为 `qq`，再调用 `message.get_by_id(msg_id, stream_id=当前会话)`。
3. 要求返回消息属于同一 `session_id`，且消息本身的 `platform` 也为 `qq`。
4. 从 `message_info.user_info.user_id` 取得目标；群聊再从 `group_info.group_id` 取得群号。
5. 群聊要求消息 `group_id` 与当前上下文一致；私聊要求消息发送者与当前私聊 `user_id` 一致。
6. 通过 Host 调用完整 API 名
   `maibot-team.snowluma-adapter.adapter.napcat.message.send_poke`。
7. 只有 SnowLuma 同时返回 `status="ok"` 和整数 `retcode=0` 才视为成功。

API 未找到、Adapter 未连接、RPC 超时、跨会话消息、非 QQ 消息、畸形消息数据以及 SnowLuma 业务失败，都会作为
`success=false` 的结构化结果返回模型，不会静默成功。

## 测试

安装开发所需 SDK 后运行标准库单元测试：

```shell
python -m pip install "maibot-plugin-sdk>=2.7.0,<3.0.0"
python -m unittest discover -s tests -v
```

单元测试覆盖最小配置 Schema、Tool 可见性、参数 Schema、空会话保护、Host 两层失败、跨会话/非 QQ 拒绝、
群聊与私聊参数差异，以及 SnowLuma `status` / `retcode` 的严格判定。发布前仍建议在真实 QQ 群聊和私聊各完成
一次端到端测试。

## Manifest 能力

插件只申请实际使用的 Host capabilities：

- `message.get_by_id`
- `api.call`

Manifest 使用 v2，`plugin_type` 为 `tool`，并显式依赖 `maibot-team.snowluma-adapter`。

开发规范参考：

- [MaiBot 插件开发文档](https://docs.mai-mai.org/plugin/)
- [MaiBot Tool 组件文档](https://docs.mai-mai.org/plugin/tools)
- [MaiBot Manifest 文档](https://docs.mai-mai.org/plugin/manifest)
- [MaiBot 插件中心贡献指南](https://github.com/Mai-with-u/plugin-repo/blob/main/CONTRIBUTING.md)

## License

[MIT](LICENSE)
