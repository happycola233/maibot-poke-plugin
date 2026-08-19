from __future__ import annotations

import json
import logging
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from plugin import PokePlugin, SNOWLUMA_SEND_POKE_API


class FakeMessageCapability:
    def __init__(
        self,
        result: Any = None,
        exception: Exception | None = None,
        recent_result: Any = None,
        recent_exception: Exception | None = None,
    ) -> None:
        self.result = result
        self.exception = exception
        self.recent_result = recent_result
        self.recent_exception = recent_exception
        self.calls: list[dict[str, Any]] = []
        self.recent_calls: list[dict[str, Any]] = []

    async def get_recent(self, chat_id: str, limit: int = 10) -> Any:
        self.recent_calls.append({"chat_id": chat_id, "limit": limit})
        if self.recent_exception is not None:
            raise self.recent_exception
        return self.recent_result

    async def get_by_id(
        self,
        message_id: str,
        *,
        stream_id: str = "",
        include_binary_data: bool = False,
    ) -> Any:
        self.calls.append(
            {
                "message_id": message_id,
                "stream_id": stream_id,
                "include_binary_data": include_binary_data,
            }
        )
        if self.exception is not None:
            raise self.exception
        return self.result


class FakeAPICapability:
    def __init__(self, result: Any = None, exception: Exception | None = None) -> None:
        self.result = result
        self.exception = exception
        self.calls: list[dict[str, Any]] = []

    async def call(self, api_name: str, *, version: str = "", **kwargs: Any) -> Any:
        self.calls.append({"api_name": api_name, "version": version, "kwargs": kwargs})
        if self.exception is not None:
            raise self.exception
        return self.result


class FakeContext:
    def __init__(self, message: FakeMessageCapability, api: FakeAPICapability) -> None:
        self.message = message
        self.api = api
        self.logger = logging.getLogger("test.maibot-poke-plugin")


def qq_message(
    *,
    message_id: str = "msg-1",
    timestamp: Any = "1000.0",
    session_id: str = "stream-1",
    platform: str = "qq",
    user_id: Any = "123456",
    group_info: Any = None,
    is_notify: bool = False,
    additional_config: Any = None,
) -> dict[str, Any]:
    return {
        "message_id": message_id,
        "timestamp": timestamp,
        "session_id": session_id,
        "platform": platform,
        "is_notify": is_notify,
        "message_info": {
            "user_info": {"user_id": user_id, "user_nickname": "测试用户"},
            "group_info": group_info,
            "additional_config": (
                {} if additional_config is None else additional_config
            ),
        },
    }


def poke_notice(
    *,
    message_id: str = "notice:notify:poke:abc123",
    timestamp: Any = "1000.0",
    session_id: str = "stream-1",
    platform: str = "qq",
    user_id: Any = "123456",
    self_id: Any = "999999",
    target_id: Any = "999999",
    group_info: Any = None,
    is_notify: bool = True,
    notice_type: str = "notify",
    notice_sub_type: str = "poke",
    additional_config: Any = None,
) -> dict[str, Any]:
    """构造与 SnowLuma Adapter 入站通知一致的消息字典。"""

    notice_config: Any = (
        {
            "self_id": self_id,
            "target_id": target_id,
            "snowluma_notice_type": notice_type,
            "snowluma_notice_sub_type": notice_sub_type,
        }
        if additional_config is None
        else additional_config
    )
    return qq_message(
        message_id=message_id,
        timestamp=timestamp,
        session_id=session_id,
        platform=platform,
        user_id=user_id,
        group_info=group_info,
        is_notify=is_notify,
        additional_config=notice_config,
    )


def build_plugin(
    message_result: Any,
    api_result: Any = None,
    *,
    message_exception: Exception | None = None,
    recent_result: Any = None,
    recent_exception: Exception | None = None,
    api_exception: Exception | None = None,
) -> tuple[PokePlugin, FakeMessageCapability, FakeAPICapability]:
    message = FakeMessageCapability(
        message_result,
        message_exception,
        recent_result,
        recent_exception,
    )
    api = FakeAPICapability(api_result, api_exception)
    plugin = PokePlugin()
    plugin._set_context(FakeContext(message, api))  # type: ignore[arg-type]
    return plugin, message, api


async def invoke_send_poke(
    plugin: PokePlugin,
    msg_id: str | None = "msg-1",
    *,
    stream_id: str = "stream-1",
    chat_id: str | None = None,
    platform: str = "qq",
    user_id: str = "123456",
    group_id: str = "",
) -> dict[str, Any]:
    """使用当前 Host 会自动注入的会话字段调用 Tool。"""

    return cast(
        dict[str, Any],
        await plugin.send_poke(
            msg_id,
            stream_id=stream_id,
            chat_id=stream_id if chat_id is None else chat_id,
            platform=platform,
            user_id=user_id,
            group_id=group_id,
        ),
    )


class ToolDeclarationTests(unittest.TestCase):
    def test_send_poke_is_visible_and_only_exposes_required_nullable_msg_id(
        self,
    ) -> None:
        self.assertEqual(
            SNOWLUMA_SEND_POKE_API,
            "maibot-team.snowluma-adapter.adapter.napcat.message.send_poke",
        )
        components = PokePlugin().get_components()
        self.assertEqual([item["name"] for item in components], ["send_poke"])
        component = components[0]

        self.assertEqual(component["type"], "TOOL")
        metadata = component["metadata"]
        self.assertEqual(metadata["visibility"], "visible")
        self.assertIn("QQ 的轻量互动", metadata["description"])
        self.assertIn("比直接 @ 或点名更含蓄", metadata["description"])
        self.assertIn("目标用户不需要先戳机器人", metadata["description"])
        self.assertIn("戳一戳某条消息的发送者", metadata["description"])
        self.assertIn("两种用法", metadata["description"])
        self.assertIn("真实的 msg_id", metadata["description"])
        self.assertIn("最新的消息是戳向机器人的戳一戳消息", metadata["description"])
        self.assertIn("就将 msg_id 设为 null", metadata["description"])
        self.assertIn("唯一锁定发起者时执行", metadata["description"])
        schema = metadata["parameters_raw"]
        self.assertEqual(set(schema["properties"]), {"msg_id"})
        self.assertEqual(schema["required"], ["msg_id"])
        self.assertIs(schema["additionalProperties"], False)
        msg_id_schema = schema["properties"]["msg_id"]
        self.assertEqual(msg_id_schema["type"], ["string", "null"])
        self.assertEqual(msg_id_schema["minLength"], 1)
        # 参数说明只讲字段本身，回戳的完整触发条件放在工具 description 里，避免重复。
        self.assertIn("必填", msg_id_schema["description"])
        self.assertIn("真实的 msg_id", msg_id_schema["description"])
        self.assertIn("回戳刚戳过机器人的人时传 null", msg_id_schema["description"])
        self.assertIn("触发条件见工具说明", msg_id_schema["description"])
        self.assertIn("也不能是通知消息的 ID", msg_id_schema["description"])


class ConfigurationTests(unittest.TestCase):
    def test_minimal_config_model_builds_webui_metadata(self) -> None:
        plugin = PokePlugin()

        self.assertTrue(plugin.has_config_model())
        self.assertEqual(
            plugin.get_default_config(),
            {
                "plugin": {
                    "enabled": True,
                    "config_version": "1.0.0",
                }
            },
        )
        normalized_config, changed = plugin.normalize_plugin_config({})
        self.assertEqual(normalized_config, plugin.get_default_config())
        self.assertTrue(changed)

        schema = PokePlugin.build_config_schema(
            plugin_id="github.happycola233.maibot-poke-plugin",
            plugin_name="MaiBot 戳一戳插件",
            plugin_version="1.2.0",
            plugin_description="测试描述",
            plugin_author="happycola233",
        )
        self.assertEqual(schema["plugin_info"]["name"], "MaiBot 戳一戳插件")
        self.assertEqual(
            schema["sections"]["plugin"]["description"],
            "MaiBot 戳一戳插件的基础启用设置。",
        )
        fields = schema["sections"]["plugin"]["fields"]
        self.assertEqual(set(fields), {"enabled", "config_version"})
        self.assertEqual(fields["enabled"]["label"], "启用插件")
        self.assertEqual(
            fields["enabled"]["hint"],
            "控制是否启用插件并向模型注册 send_poke 工具。",
        )
        self.assertIs(fields["enabled"]["default"], True)
        self.assertIs(fields["enabled"]["hidden"], False)
        self.assertEqual(fields["config_version"]["label"], "配置版本")
        self.assertIs(fields["config_version"]["hidden"], True)
        self.assertIs(fields["config_version"]["disabled"], True)


class ManifestContractTests(unittest.TestCase):
    def test_manifest_declares_tool_contract_and_adapter_dependency(self) -> None:
        manifest_path = Path(__file__).resolve().parents[1] / "_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["manifest_version"], 2)
        self.assertEqual(manifest["id"], "github.happycola233.maibot-poke-plugin")
        self.assertEqual(manifest["version"], "1.2.1")
        self.assertEqual(manifest["plugin_type"], "tool")
        self.assertEqual(manifest["sdk"]["min_version"], "2.7.0")
        self.assertEqual(
            set(manifest["capabilities"]),
            {"message.get_by_id", "message.get_recent", "api.call"},
        )
        plugin_dependencies = {
            dependency["id"]: dependency
            for dependency in manifest["dependencies"]
            if dependency.get("type") == "plugin"
        }
        self.assertIn("maibot-team.snowluma-adapter", plugin_dependencies)


class SendPokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_blank_msg_id_is_rejected_before_query(self) -> None:
        for blank_msg_id in ("", " ", " \t\n"):
            with self.subTest(msg_id=repr(blank_msg_id)):
                plugin, message, api = build_plugin(qq_message())

                result = await invoke_send_poke(plugin, msg_id=blank_msg_id)

                self.assertFalse(result["success"])
                self.assertEqual(result["stage"], "validation")
                self.assertIn("空字符串或纯空白", result["content"])
                self.assertIn("不等于 null", result["content"])
                self.assertIn("真实的 msg_id", result["content"])
                self.assertIn("将 msg_id 显式传为 null", result["content"])
                self.assertEqual(message.calls, [])
                self.assertEqual(message.recent_calls, [])
                self.assertEqual(api.calls, [])

    async def test_null_msg_id_uses_recent_poke_fallback(self) -> None:
        notice = poke_notice()
        plugin, message, api = build_plugin(
            notice,
            {"status": "ok", "retcode": 0, "data": None},
            recent_result=[notice],
        )

        with patch("plugin.time.time", return_value=1000.0):
            result = await plugin.send_poke(
                msg_id=None,
                stream_id="stream-1",
                chat_id="stream-1",
                platform="qq",
                user_id="123456",
                group_id="",
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["target_source"], "recent_poke")
        self.assertNotIn("msg_id", result)
        self.assertEqual(
            message.recent_calls,
            [{"chat_id": "stream-1", "limit": 20}],
        )
        self.assertEqual(api.calls[0]["kwargs"], {"user_id": "123456"})

    async def test_non_string_non_null_msg_id_is_rejected_before_query(self) -> None:
        plugin, message, api = build_plugin(qq_message())

        result = await plugin.send_poke(123, stream_id="stream-1")

        self.assertFalse(result["success"])
        self.assertIn("必须是字符串或 null", result["content"])
        self.assertEqual(message.calls, [])
        self.assertEqual(message.recent_calls, [])
        self.assertEqual(api.calls, [])

    async def test_explicit_msg_id_rejects_notification_messages(self) -> None:
        notice = poke_notice()
        plugin, message, api = build_plugin(notice)

        result = await invoke_send_poke(
            plugin,
            msg_id=str(notice["message_id"]),
        )

        self.assertFalse(result["success"])
        self.assertIn("不能使用通知消息 ID", result["content"])
        self.assertEqual(message.recent_calls, [])
        self.assertEqual(api.calls, [])

    async def test_missing_stream_id_is_rejected_before_query(self) -> None:
        plugin, message, api = build_plugin(qq_message())

        result = await plugin.send_poke("msg-1")

        self.assertFalse(result["success"])
        self.assertIn("stream_id", result["content"])
        self.assertEqual(message.calls, [])
        self.assertEqual(message.recent_calls, [])
        self.assertEqual(api.calls, [])

    async def test_non_qq_context_is_rejected_before_query(self) -> None:
        plugin, message, api = build_plugin(qq_message())

        result = await invoke_send_poke(plugin, platform="discord")

        self.assertFalse(result["success"])
        self.assertIn("不是 QQ 会话", result["content"])
        self.assertEqual(message.calls, [])
        self.assertEqual(message.recent_calls, [])
        self.assertEqual(api.calls, [])

    async def test_inconsistent_injected_chat_ids_are_rejected_before_query(
        self,
    ) -> None:
        plugin, message, api = build_plugin(qq_message())

        result = await invoke_send_poke(plugin, chat_id="another-stream")

        self.assertFalse(result["success"])
        self.assertIn("stream_id 与 chat_id 不一致", result["content"])
        self.assertEqual(message.calls, [])
        self.assertEqual(message.recent_calls, [])
        self.assertEqual(api.calls, [])

    async def test_recent_group_poke_resolves_hidden_notice_id(self) -> None:
        notice = poke_notice(group_info={"group_id": "654321", "group_name": "测试群"})
        plugin, message, api = build_plugin(
            notice,
            {"status": "ok", "retcode": 0, "data": None},
            recent_result=[notice, qq_message(timestamp="900.0")],
        )

        with patch("plugin.time.time", return_value=1001.0):
            result = await invoke_send_poke(
                plugin,
                msg_id=None,
                group_id="654321",
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["target_source"], "recent_poke")
        self.assertNotIn("msg_id", result)
        self.assertIn("最新的戳一戳通知", result["content"])
        self.assertEqual(
            message.recent_calls,
            [{"chat_id": "stream-1", "limit": 20}],
        )
        self.assertEqual(
            message.calls,
            [
                {
                    "message_id": "notice:notify:poke:abc123",
                    "stream_id": "stream-1",
                    "include_binary_data": False,
                }
            ],
        )
        self.assertEqual(
            api.calls[0]["kwargs"],
            {"user_id": "123456", "group_id": "654321"},
        )

    async def test_recent_private_poke_only_passes_user_id(self) -> None:
        notice = poke_notice()
        plugin, message, api = build_plugin(
            notice,
            {"status": "ok", "retcode": 0, "data": None},
            recent_result=[notice],
        )

        with patch("plugin.time.time", return_value=1000.0):
            result = await invoke_send_poke(plugin, msg_id=None)

        self.assertTrue(result["success"])
        self.assertEqual(result["chat_type"], "private")
        self.assertEqual(message.calls[0]["message_id"], notice["message_id"])
        self.assertEqual(api.calls[0]["kwargs"], {"user_id": "123456"})

    async def test_same_timestamp_pokes_require_one_unique_actor(self) -> None:
        first = poke_notice(message_id="notice:notify:poke:aaa", user_id="111111")
        same_actor = poke_notice(
            message_id="notice:notify:poke:bbb",
            user_id="111111",
        )
        other_actor = poke_notice(
            message_id="notice:notify:poke:ccc",
            user_id="222222",
        )

        plugin, message, api = build_plugin(
            same_actor,
            {"status": "ok", "retcode": 0},
            recent_result=[same_actor, first],
        )
        with patch("plugin.time.time", return_value=1000.0):
            result = await invoke_send_poke(
                plugin,
                msg_id=None,
                user_id="111111",
            )

        self.assertTrue(result["success"])
        self.assertEqual(message.calls[0]["message_id"], "notice:notify:poke:bbb")

        plugin, message, api = build_plugin(
            first,
            {"status": "ok", "retcode": 0},
            recent_result=[first, other_actor],
        )
        with patch("plugin.time.time", return_value=1000.0):
            result = await invoke_send_poke(plugin, msg_id=None)

        self.assertFalse(result["success"])
        self.assertIn("多位用户", result["content"])
        self.assertEqual(message.calls, [])
        self.assertEqual(api.calls, [])

    async def test_recent_query_failures_are_explicit(self) -> None:
        cases: list[tuple[Any, Exception | None, str]] = [
            ({"success": False, "error": "历史库不可用"}, None, "历史库不可用"),
            (None, RuntimeError("最近消息 RPC 已断开"), "最近消息 RPC 已断开"),
            (None, None, "无效的最近消息列表"),
            ([], None, "没有可用于回戳"),
        ]
        for recent_result, exception, expected in cases:
            with self.subTest(expected=expected):
                plugin, message, api = build_plugin(
                    poke_notice(),
                    recent_result=recent_result,
                    recent_exception=exception,
                )

                result = await invoke_send_poke(plugin, msg_id=None)

                self.assertFalse(result["success"])
                self.assertEqual(result["stage"], "message.get_recent")
                self.assertIn(expected, result["content"])
                self.assertEqual(message.calls, [])
                self.assertEqual(api.calls, [])

    async def test_recent_poke_requires_fresh_valid_latest_timestamp(self) -> None:
        cases = [
            (poke_notice(timestamp="800.0"), 1000.0, "不在安全回戳范围内"),
            (poke_notice(timestamp="1010.0"), 1000.0, "不在安全回戳范围内"),
            (poke_notice(timestamp="nan"), 1000.0, "缺少有效时间"),
            (poke_notice(timestamp="inf"), 1000.0, "缺少有效时间"),
            (poke_notice(timestamp="invalid"), 1000.0, "缺少有效时间"),
        ]
        for notice, current_time, expected in cases:
            with self.subTest(timestamp=notice["timestamp"]):
                plugin, message, api = build_plugin(
                    notice,
                    recent_result=[notice],
                )

                with patch("plugin.time.time", return_value=current_time):
                    result = await invoke_send_poke(plugin, msg_id=None)

                self.assertFalse(result["success"])
                self.assertIn(expected, result["content"])
                self.assertEqual(message.calls, [])
                self.assertEqual(api.calls, [])

    async def test_recent_fallback_rejects_non_poke_latest_messages(self) -> None:
        invalid_candidates = [
            qq_message(timestamp="1001.0"),
            poke_notice(is_notify=False),
            poke_notice(notice_type="group_recall"),
            poke_notice(notice_sub_type="other"),
            poke_notice(target_id="888888"),
            poke_notice(self_id=""),
            poke_notice(user_id="999999"),
            poke_notice(session_id="stream-2"),
            poke_notice(platform="discord"),
            poke_notice(message_id="ordinary-id"),
            poke_notice(additional_config="invalid"),
        ]
        for candidate in invalid_candidates:
            with self.subTest(candidate=candidate):
                plugin, message, api = build_plugin(
                    candidate,
                    recent_result=[candidate],
                )

                with patch("plugin.time.time", return_value=1001.0):
                    result = await invoke_send_poke(plugin, msg_id=None)

                self.assertFalse(result["success"])
                self.assertIn("不是可确认的", result["content"])
                self.assertIn("请提供 msg_id", result["content"])
                self.assertEqual(message.calls, [])
                self.assertEqual(api.calls, [])

    async def test_newer_normal_message_prevents_reusing_an_older_poke(self) -> None:
        notice = poke_notice(timestamp="1000.0")
        newer_message = qq_message(timestamp="1001.0")
        plugin, message, api = build_plugin(
            notice,
            recent_result=[notice, newer_message],
        )

        with patch("plugin.time.time", return_value=1001.0):
            result = await invoke_send_poke(plugin, msg_id=None)

        self.assertFalse(result["success"])
        self.assertIn("不是可确认的", result["content"])
        self.assertIn("请提供 msg_id", result["content"])
        self.assertEqual(message.calls, [])
        self.assertEqual(api.calls, [])

    async def test_recent_notice_still_uses_scoped_get_by_id_result(self) -> None:
        notice = poke_notice()
        plugin, message, api = build_plugin(None, recent_result=[notice])

        with patch("plugin.time.time", return_value=1000.0):
            result = await invoke_send_poke(plugin, msg_id=None)

        self.assertFalse(result["success"])
        self.assertIn("找不到", result["content"])
        self.assertNotIn("msg_id", result)
        self.assertEqual(message.calls[0]["stream_id"], "stream-1")
        self.assertEqual(api.calls, [])

    async def test_recent_notice_identity_must_match_get_by_id_result(self) -> None:
        recent_notice = poke_notice(
            group_info={"group_id": "654321", "group_name": "测试群"}
        )
        changed_notice = poke_notice(
            user_id="222222",
            group_info={"group_id": "654321", "group_name": "测试群"},
        )
        plugin, message, api = build_plugin(
            changed_notice,
            {"status": "ok", "retcode": 0},
            recent_result=[recent_notice],
        )

        with patch("plugin.time.time", return_value=1000.0):
            result = await invoke_send_poke(
                plugin,
                msg_id=None,
                group_id="654321",
            )

        self.assertFalse(result["success"])
        self.assertIn("身份不一致", result["content"])
        self.assertEqual(len(message.calls), 1)
        self.assertEqual(api.calls, [])

    async def test_group_poke_uses_message_sender_and_group(self) -> None:
        plugin, message, api = build_plugin(
            qq_message(group_info={"group_id": "654321", "group_name": "测试群"}),
            {"status": "ok", "retcode": 0, "data": None},
        )

        result = await invoke_send_poke(plugin, group_id="654321")

        self.assertTrue(result["success"])
        self.assertEqual(result["chat_type"], "group")
        self.assertEqual(result["target_source"], "msg_id")
        self.assertEqual(message.recent_calls, [])
        self.assertEqual(
            message.calls,
            [
                {
                    "message_id": "msg-1",
                    "stream_id": "stream-1",
                    "include_binary_data": False,
                }
            ],
        )
        self.assertEqual(
            api.calls,
            [
                {
                    "api_name": SNOWLUMA_SEND_POKE_API,
                    "version": "1",
                    "kwargs": {"user_id": "123456", "group_id": "654321"},
                }
            ],
        )

    async def test_private_poke_only_passes_user_id(self) -> None:
        plugin, message, api = build_plugin(
            qq_message(group_info=None),
            {"status": "ok", "retcode": 0, "data": None},
        )

        result = await invoke_send_poke(plugin)

        self.assertTrue(result["success"])
        self.assertEqual(result["chat_type"], "private")
        self.assertEqual(message.recent_calls, [])
        self.assertEqual(api.calls[0]["kwargs"], {"user_id": "123456"})

    async def test_host_query_failures_are_explicit(self) -> None:
        cases = [
            ({"success": False, "error": "数据库不可用"}, None, "数据库不可用"),
            (None, None, "找不到"),
            (None, RuntimeError("RPC 已断开"), "RPC 已断开"),
        ]
        for message_result, exception, expected in cases:
            with self.subTest(expected=expected):
                plugin, _, api = build_plugin(
                    message_result, message_exception=exception
                )

                result = await invoke_send_poke(plugin)

                self.assertFalse(result["success"])
                self.assertIn(expected, result["content"])
                self.assertEqual(api.calls, [])

    async def test_cross_session_and_non_qq_messages_are_rejected(self) -> None:
        cases = [
            (qq_message(session_id="stream-2"), "跨会话"),
            (qq_message(platform="discord"), "不是 QQ 消息"),
        ]
        for message_result, expected in cases:
            with self.subTest(expected=expected):
                plugin, _, api = build_plugin(message_result)

                result = await invoke_send_poke(plugin)

                self.assertFalse(result["success"])
                self.assertIn(expected, result["content"])
                self.assertEqual(api.calls, [])

    async def test_injected_conversation_identity_must_match_target_message(
        self,
    ) -> None:
        cases = [
            (qq_message(), {"user_id": "999999"}, "当前私聊会话"),
            (
                qq_message(group_info={"group_id": "654321", "group_name": "测试群"}),
                {"group_id": "111111"},
                "当前 QQ 群聊",
            ),
        ]
        for message_result, context_overrides, expected in cases:
            with self.subTest(expected=expected):
                plugin, _, api = build_plugin(message_result)

                result = await invoke_send_poke(plugin, **context_overrides)

                self.assertFalse(result["success"])
                self.assertIn(expected, result["content"])
                self.assertEqual(api.calls, [])

    async def test_malformed_target_ids_are_rejected(self) -> None:
        missing_group_info = qq_message()
        del missing_group_info["message_info"]["group_info"]
        cases = [
            (qq_message(user_id="not-a-qq-id"), "user_id"),
            (qq_message(group_info={}), "group_id"),
            (qq_message(group_info="invalid"), "group_info"),
            (missing_group_info, "group_info"),
        ]
        for message_result, expected in cases:
            with self.subTest(expected=expected):
                plugin, _, api = build_plugin(message_result)

                result = await invoke_send_poke(plugin)

                self.assertFalse(result["success"])
                self.assertIn(expected, result["content"])
                self.assertEqual(api.calls, [])

    async def test_host_api_failure_and_exception_are_explicit(self) -> None:
        cases = [
            ({"success": False, "error": "Adapter 未加载"}, None, "Adapter 未加载"),
            (None, TimeoutError("调用超时"), "调用超时"),
        ]
        for api_result, exception, expected in cases:
            with self.subTest(expected=expected):
                plugin, _, _ = build_plugin(
                    qq_message(), api_result, api_exception=exception
                )

                result = await invoke_send_poke(plugin)

                self.assertFalse(result["success"])
                self.assertIn(expected, result["content"])

    async def test_invalid_snowluma_result_is_rejected(self) -> None:
        plugin, _, _ = build_plugin(qq_message(), None)

        result = await invoke_send_poke(plugin)

        self.assertFalse(result["success"])
        self.assertIn("无效结果", result["content"])

    async def test_snowluma_requires_exact_ok_status_and_integer_zero_retcode(
        self,
    ) -> None:
        cases = [
            {"status": "failed", "retcode": 100, "wording": "发送失败"},
            {"status": "ok", "retcode": 1},
            {"status": "ok", "retcode": "0"},
            {"status": "ok", "retcode": False},
            {"retcode": 0},
        ]
        for api_result in cases:
            with self.subTest(api_result=api_result):
                plugin, _, _ = build_plugin(qq_message(), api_result)

                result = await invoke_send_poke(plugin)

                self.assertFalse(result["success"])
                self.assertEqual(result["stage"], "snowluma")
                self.assertIn("status=", result["content"])


if __name__ == "__main__":
    unittest.main()
