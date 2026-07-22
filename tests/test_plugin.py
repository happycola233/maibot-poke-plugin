from __future__ import annotations

import json
import logging
import unittest
from pathlib import Path
from typing import Any

from plugin import PokePlugin, SNOWLUMA_SEND_POKE_API


class FakeMessageCapability:
    def __init__(self, result: Any = None, exception: Exception | None = None) -> None:
        self.result = result
        self.exception = exception
        self.calls: list[dict[str, Any]] = []

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
    session_id: str = "stream-1",
    platform: str = "qq",
    user_id: Any = "123456",
    group_info: Any = None,
) -> dict[str, Any]:
    return {
        "message_id": "msg-1",
        "session_id": session_id,
        "platform": platform,
        "message_info": {
            "user_info": {"user_id": user_id, "user_nickname": "测试用户"},
            "group_info": group_info,
        },
    }


def build_plugin(
    message_result: Any,
    api_result: Any = None,
    *,
    message_exception: Exception | None = None,
    api_exception: Exception | None = None,
) -> tuple[PokePlugin, FakeMessageCapability, FakeAPICapability]:
    message = FakeMessageCapability(message_result, message_exception)
    api = FakeAPICapability(api_result, api_exception)
    plugin = PokePlugin()
    plugin._set_context(FakeContext(message, api))  # type: ignore[arg-type]
    return plugin, message, api


async def invoke_send_poke(
    plugin: PokePlugin,
    msg_id: str = "msg-1",
    *,
    stream_id: str = "stream-1",
    chat_id: str | None = None,
    platform: str = "qq",
    user_id: str = "123456",
    group_id: str = "",
) -> dict[str, Any]:
    """Invoke the Tool with the context fields injected by the current Host."""

    return await plugin.send_poke(
        msg_id,
        stream_id=stream_id,
        chat_id=stream_id if chat_id is None else chat_id,
        platform=platform,
        user_id=user_id,
        group_id=group_id,
    )


class ToolDeclarationTests(unittest.TestCase):
    def test_send_poke_is_visible_and_only_exposes_msg_id(self) -> None:
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
        self.assertIn("QQ 的轻量互动功能", metadata["description"])
        self.assertIn("比直接 @ 或点名更不明显、更含蓄", metadata["description"])
        self.assertIn("目标用户不需要先戳机器人", metadata["description"])
        self.assertIn("真实的戳一戳", metadata["description"])
        schema = metadata["parameters_raw"]
        self.assertEqual(set(schema["properties"]), {"msg_id"})
        self.assertEqual(schema["required"], ["msg_id"])
        self.assertIs(schema["additionalProperties"], False)


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
            plugin_version="1.0.0",
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
        self.assertEqual(manifest["plugin_type"], "tool")
        self.assertEqual(manifest["sdk"]["min_version"], "2.7.0")
        self.assertEqual(
            set(manifest["capabilities"]), {"message.get_by_id", "api.call"}
        )
        plugin_dependencies = {
            dependency["id"]: dependency
            for dependency in manifest["dependencies"]
            if dependency.get("type") == "plugin"
        }
        self.assertIn("maibot-team.snowluma-adapter", plugin_dependencies)


class SendPokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_blank_msg_id_is_rejected_before_query(self) -> None:
        plugin, message, api = build_plugin(qq_message())

        result = await plugin.send_poke("   ", stream_id="stream-1")

        self.assertFalse(result["success"])
        self.assertIn("msg_id", result["content"])
        self.assertEqual(message.calls, [])
        self.assertEqual(api.calls, [])

    async def test_missing_stream_id_is_rejected_before_query(self) -> None:
        plugin, message, api = build_plugin(qq_message())

        result = await plugin.send_poke("msg-1")

        self.assertFalse(result["success"])
        self.assertIn("stream_id", result["content"])
        self.assertEqual(message.calls, [])
        self.assertEqual(api.calls, [])

    async def test_non_qq_context_is_rejected_before_query(self) -> None:
        plugin, message, api = build_plugin(qq_message())

        result = await invoke_send_poke(plugin, platform="discord")

        self.assertFalse(result["success"])
        self.assertIn("不是 QQ 会话", result["content"])
        self.assertEqual(message.calls, [])
        self.assertEqual(api.calls, [])

    async def test_inconsistent_injected_chat_ids_are_rejected_before_query(
        self,
    ) -> None:
        plugin, message, api = build_plugin(qq_message())

        result = await invoke_send_poke(plugin, chat_id="another-stream")

        self.assertFalse(result["success"])
        self.assertIn("stream_id 与 chat_id 不一致", result["content"])
        self.assertEqual(message.calls, [])
        self.assertEqual(api.calls, [])

    async def test_group_poke_uses_message_sender_and_group(self) -> None:
        plugin, message, api = build_plugin(
            qq_message(group_info={"group_id": "654321", "group_name": "测试群"}),
            {"status": "ok", "retcode": 0, "data": None},
        )

        result = await invoke_send_poke(plugin, group_id="654321")

        self.assertTrue(result["success"])
        self.assertEqual(result["chat_type"], "group")
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
        plugin, _, api = build_plugin(
            qq_message(group_info=None),
            {"status": "ok", "retcode": 0, "data": None},
        )

        result = await invoke_send_poke(plugin)

        self.assertTrue(result["success"])
        self.assertEqual(result["chat_type"], "private")
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
