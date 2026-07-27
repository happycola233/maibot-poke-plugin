"""将 SnowLuma 的 QQ 戳一戳能力注册为 MaiBot LLM Tool。"""

from __future__ import annotations

from collections.abc import Mapping
import math
import time
from typing import Any, ClassVar

from maibot_sdk import Field, MaiBotPlugin, PluginConfigBase, Tool


SNOWLUMA_SEND_POKE_API = "maibot-team.snowluma-adapter.adapter.napcat.message.send_poke"
RECENT_POKE_LIMIT = 20
RECENT_POKE_MAX_AGE_SECONDS = 120.0
RECENT_POKE_FUTURE_TOLERANCE_SECONDS = 5.0
POKE_NOTICE_ID_PREFIX = "notice:notify:poke:"
PokeNoticeIdentity = tuple[str, str]


class PluginSectionConfig(PluginConfigBase):
    """MaiBot 戳一戳插件的基础启用设置。"""

    __ui_label__: ClassVar[str] = "插件设置"
    __ui_icon__: ClassVar[str] = "settings"
    __ui_order__: ClassVar[int] = 0

    enabled: bool = Field(
        default=True,
        description="是否启用 MaiBot 戳一戳插件",
        json_schema_extra={
            "label": "启用插件",
            "hint": "控制是否启用插件并向模型注册 send_poke 工具。",
        },
    )
    config_version: str = Field(
        default="1.0.0",
        description="配置版本",
        json_schema_extra={
            "label": "配置版本",
            "hidden": True,
            "disabled": True,
        },
    )


class PokePluginConfig(PluginConfigBase):
    """仅包含标准插件元配置，不提供戳一戳行为选项。"""

    plugin: PluginSectionConfig = Field(
        default_factory=PluginSectionConfig,
        description="插件基础设置",
    )


class PokePlugin(MaiBotPlugin):
    """允许模型戳一戳当前 QQ 会话中某条消息的发送者。"""

    config_model: ClassVar[type[PluginConfigBase] | None] = PokePluginConfig

    async def on_load(self) -> None:
        """记录插件已加载。"""

        self.ctx.logger.info("MaiBot 戳一戳插件已加载")

    async def on_unload(self) -> None:
        """记录插件已卸载。"""

        self.ctx.logger.info("MaiBot 戳一戳插件已卸载")

    async def on_config_update(
        self, scope: str, config_data: dict[str, Any], version: str
    ) -> None:
        """忽略配置更新；标准启用状态由 Host 负责管理。"""

        del scope, config_data, version

    def get_components(self) -> list[dict[str, Any]]:
        """确保 MaiBot SDK 2.7.0 运行时仍能正确读取 Tool 可见性。"""

        components = super().get_components()
        for component in components:
            if component.get("name") != "send_poke" or component.get("type") != "TOOL":
                continue
            metadata = component.get("metadata")
            if isinstance(metadata, dict):
                # SDK 2.7.0 会把装饰器的自定义元数据多嵌套一层，因此在导出组件时显式校正。
                metadata["visibility"] = "visible"
        return components

    @Tool(
        "send_poke",
        description=(
            "戳一戳是 QQ 的轻量互动功能，可以提醒某人或引起对方注意，比直接 @ 或点名更含蓄。"
            "当群聊或私聊的语境合适时，可以戳一戳某条消息的发送者（目标用户不需要先戳机器人）。"
            "有两种用法：①想戳某条普通消息的发送者，就传入这条消息真实的 msg_id；"
            "②想回戳刚戳过机器人的人，就将 msg_id 设为 null。"
            "插件只会在本会话最新的消息是戳向机器人的戳一戳消息，且能唯一锁定发起者时执行。"
            "不符合以上情形就不要调用，也不要使用其他会话或平台的消息。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "msg_id": {
                    "type": ["string", "null"],
                    "description": (
                        "必填。要戳某条普通消息的发送者时，填这条消息在当前 QQ 会话里真实的 msg_id；"
                        "它不能为空，也不能是通知消息的 ID。"
                        "想回戳刚戳过机器人的人时传 null（触发条件见工具说明）。"
                    ),
                    "minLength": 1,
                }
            },
            "required": ["msg_id"],
            "additionalProperties": False,
        },
        visibility="visible",
    )
    async def send_poke(
        self, msg_id: str | None = None, stream_id: str = "", **kwargs: Any
    ) -> dict[str, Any]:
        """确认目标属于当前会话后，戳一戳该消息或最近通知的发送者。"""

        # 对外 Schema 要求显式传 null；默认 None 仅保留旧调用链的安全兼容性。
        if msg_id is not None and not isinstance(msg_id, str):
            return self._failure(
                "发送戳一戳失败：msg_id 必须是字符串或 null。", stage="validation"
            )
        message_id = str(msg_id or "").strip()
        if msg_id is not None and not message_id:
            return self._failure(
                "发送戳一戳失败：msg_id 是空字符串或纯空白，这既不是合法的消息 ID，也不等于 null，本次未执行。"
                "想戳某条普通消息的发送者，请填这条消息真实的 msg_id；"
                "想回戳刚戳过机器人的人，请将 msg_id 显式传为 null。",
                stage="validation",
            )
        current_stream_id = str(stream_id or "").strip()
        if not current_stream_id:
            return self._failure(
                "发送戳一戳失败：Host 未注入当前会话的 stream_id，已拒绝进行全局消息查询。",
                stage="validation",
            )

        # stream_id 与 chat_id 都由 Host 注入；两者一致才允许继续，避免查询边界退化。
        current_chat_id = str(kwargs.get("chat_id") or "").strip()
        if not current_chat_id:
            return self._failure(
                "发送戳一戳失败：Host 未注入当前会话的 chat_id，无法确认会话边界。",
                stage="validation",
            )
        if current_stream_id != current_chat_id:
            return self._failure(
                "发送戳一戳失败：Host 注入的 stream_id 与 chat_id 不一致，已拒绝查询消息。",
                stage="validation",
            )

        context_platform = str(kwargs.get("platform") or "").strip().casefold()
        if context_platform != "qq":
            return self._failure(
                "发送戳一戳失败：当前会话不是 QQ 会话，或 Host 未注入平台信息。",
                stage="validation",
                platform=context_platform or None,
            )

        target_source = "msg_id"
        expected_recent_identity: PokeNoticeIdentity | None = None
        if msg_id is None:
            # 通知 ID 不展示给模型时，只查看当前会话的最新时间点；不在历史通知中猜测目标。
            (
                expected_recent_identity,
                resolution_error,
            ) = await self._resolve_recent_poke_identity(current_stream_id)
            if resolution_error is not None:
                return resolution_error
            if expected_recent_identity is None:
                return self._failure(
                    "发送戳一戳失败：无法确定最近戳一戳通知的身份。",
                    stage="message.get_recent",
                )
            message_id = expected_recent_identity[0]
            target_source = "recent_poke"

        # 查询时始终附带当前 stream_id，不允许仅凭全局唯一性假设读取其他会话的消息。
        try:
            message_result = await self.ctx.message.get_by_id(
                message_id,
                stream_id=current_stream_id,
                include_binary_data=False,
            )
        except Exception as exc:
            return self._failure(
                f"发送戳一戳失败：调用 Host 的 message.get_by_id 时发生异常：{exc}",
                stage="message.get_by_id",
            )

        host_error = self._host_error(message_result)
        if host_error is not None:
            return self._failure(
                f"发送戳一戳失败：Host 查询消息失败：{host_error}",
                stage="message.get_by_id",
            )
        if message_result is None:
            missing_message_details = (
                {"msg_id": message_id} if target_source == "msg_id" else {}
            )
            return self._failure(
                "发送戳一戳失败：当前会话中找不到该 msg_id 对应的消息；不会查询或操作其他会话。",
                stage="message.get_by_id",
                **missing_message_details,
            )
        if not isinstance(message_result, Mapping):
            return self._failure(
                "发送戳一戳失败：Host 返回了无效的消息数据。",
                stage="message.get_by_id",
            )

        message = message_result
        message_stream_id = str(message.get("session_id") or "").strip()
        if not message_stream_id:
            return self._failure(
                "发送戳一戳失败：消息缺少 session_id，无法确认会话归属。",
                stage="validation",
            )
        if message_stream_id != current_stream_id:
            return self._failure(
                "发送戳一戳失败：目标消息不属于当前会话，已拒绝跨会话操作。",
                stage="validation",
            )

        message_platform = str(message.get("platform") or "").strip().casefold()
        if message_platform != "qq":
            return self._failure(
                "发送戳一戳失败：目标消息不是 QQ 消息。",
                stage="validation",
                platform=message_platform or None,
            )

        if target_source == "msg_id" and message.get("is_notify") is True:
            return self._failure(
                "发送戳一戳失败：显式 msg_id 必须指向用户发送的普通消息，不能使用通知消息 ID。",
                stage="validation",
            )
        if target_source == "recent_poke":
            # get_recent 与 get_by_id 的结果必须指向同一通知身份，避免查询之间目标发生变化。
            confirmed_identity = self._poke_notice_identity(
                message,
                current_stream_id,
            )
            if confirmed_identity != expected_recent_identity:
                return self._failure(
                    "发送戳一戳失败：最近戳一戳通知在复核时身份不一致，已拒绝发送。",
                    stage="validation",
                )

        message_info = message.get("message_info")
        if not isinstance(message_info, Mapping):
            return self._failure(
                "发送戳一戳失败：目标消息缺少有效的 message_info。",
                stage="validation",
            )
        user_info = message_info.get("user_info")
        if not isinstance(user_info, Mapping):
            return self._failure(
                "发送戳一戳失败：目标消息缺少有效的发送者信息。",
                stage="validation",
            )

        user_id = self._qq_id(user_info.get("user_id"))
        if user_id is None:
            return self._failure(
                "发送戳一戳失败：目标消息的发送者 user_id 不是有效的 QQ 号。",
                stage="validation",
            )

        if "group_info" not in message_info:
            return self._failure(
                "发送戳一戳失败：目标消息缺少 group_info，无法判断群聊或私聊。",
                stage="validation",
            )

        raw_group_info = message_info.get("group_info")
        api_args: dict[str, str] = {"user_id": user_id}
        group_id: str | None = None
        if raw_group_info is None:
            # 私聊不向底层 API 传 group_id，并再次确认发送者就是当前私聊对象。
            raw_context_group_id = str(kwargs.get("group_id") or "").strip()
            context_user_id = self._qq_id(kwargs.get("user_id"))
            if raw_context_group_id:
                return self._failure(
                    "发送戳一戳失败：目标消息是私聊消息，但当前 Host 上下文属于群聊。",
                    stage="validation",
                )
            if context_user_id != user_id:
                return self._failure(
                    "发送戳一戳失败：目标消息的发送者不属于当前私聊会话。",
                    stage="validation",
                )
            chat_type = "private"
        elif isinstance(raw_group_info, Mapping):
            # 群聊必须同时校验消息群号和当前上下文群号，防止跨群操作。
            group_id = self._qq_id(raw_group_info.get("group_id"))
            if group_id is None:
                return self._failure(
                    "发送戳一戳失败：群聊消息缺少有效的 group_id。",
                    stage="validation",
                )
            group_context_id = self._qq_id(kwargs.get("group_id"))
            if group_context_id != group_id:
                return self._failure(
                    "发送戳一戳失败：目标消息不属于当前 QQ 群聊。",
                    stage="validation",
                )
            api_args["group_id"] = group_id
            chat_type = "group"
        else:
            return self._failure(
                "发送戳一戳失败：目标消息的 group_info 格式无效。",
                stage="validation",
            )

        try:
            snowluma_result = await self.ctx.api.call(
                SNOWLUMA_SEND_POKE_API,
                version="1",
                **api_args,
            )
        except Exception as exc:
            return self._failure(
                f"发送戳一戳失败：调用 SnowLuma Adapter API 时发生异常：{exc}",
                stage="api.call",
            )

        host_error = self._host_error(snowluma_result)
        if host_error is not None:
            return self._failure(
                f"发送戳一戳失败：Host 调用 SnowLuma Adapter API 失败：{host_error}",
                stage="api.call",
            )
        if not isinstance(snowluma_result, Mapping):
            return self._failure(
                "发送戳一戳失败：SnowLuma Adapter 返回了无效结果。",
                stage="snowluma",
            )

        status = str(snowluma_result.get("status") or "").strip().casefold()
        retcode = snowluma_result.get("retcode")
        # Host 调用成功不等于 QQ 操作成功；必须继续严格检查 SnowLuma 的业务结果。
        if status != "ok" or type(retcode) is not int or retcode != 0:
            detail = str(
                snowluma_result.get("wording")
                or snowluma_result.get("message")
                or "SnowLuma 未提供错误详情"
            ).strip()
            return self._failure(
                f"发送戳一戳失败：SnowLuma 返回 status={status or '<missing>'}、retcode={retcode!r}：{detail}",
                stage="snowluma",
                status=status or None,
                retcode=retcode,
            )

        target = (
            f"群 {group_id} 中的 QQ 用户 {user_id}"
            if group_id is not None
            else f"私聊 QQ 用户 {user_id}"
        )
        source_description = (
            "根据当前会话最新的戳一戳通知，" if target_source == "recent_poke" else ""
        )
        result: dict[str, Any] = {
            "success": True,
            "content": f"已{source_description}成功戳一戳{target}。",
            "user_id": user_id,
            "group_id": group_id,
            "chat_type": chat_type,
            "target_source": target_source,
            "status": status,
            "retcode": retcode,
        }
        if target_source == "msg_id":
            result["msg_id"] = message_id
        return result

    async def _resolve_recent_poke_identity(
        self, current_stream_id: str
    ) -> tuple[PokeNoticeIdentity | None, dict[str, Any] | None]:
        """从当前会话的最新消息中解析可安全回戳的通知身份。"""

        try:
            recent_result = await self.ctx.message.get_recent(
                current_stream_id,
                limit=RECENT_POKE_LIMIT,
            )
        except Exception as exc:
            return None, self._failure(
                f"发送戳一戳失败：调用 Host 的 message.get_recent 时发生异常：{exc}",
                stage="message.get_recent",
            )

        host_error = self._host_error(recent_result)
        if host_error is not None:
            return None, self._failure(
                f"发送戳一戳失败：Host 查询最近消息失败：{host_error}",
                stage="message.get_recent",
            )
        if not isinstance(recent_result, list):
            return None, self._failure(
                "发送戳一戳失败：Host 返回了无效的最近消息列表。",
                stage="message.get_recent",
            )
        if not recent_result:
            return None, self._failure(
                "发送戳一戳失败：当前 QQ 会话中没有可用于回戳的最近消息。",
                stage="message.get_recent",
            )

        timestamped_messages: list[tuple[float, Mapping[str, Any]]] = []
        for recent_message in recent_result:
            if not isinstance(recent_message, Mapping):
                return None, self._failure(
                    "发送戳一戳失败：Host 返回的最近消息格式无效。",
                    stage="message.get_recent",
                )
            message_timestamp = self._timestamp(recent_message.get("timestamp"))
            if message_timestamp is None:
                return None, self._failure(
                    "发送戳一戳失败：最近消息缺少有效时间，无法判断通知是否仍然新鲜。",
                    stage="message.get_recent",
                )
            timestamped_messages.append((message_timestamp, recent_message))

        latest_timestamp = max(item[0] for item in timestamped_messages)
        latest_messages = [
            message
            for message_timestamp, message in timestamped_messages
            if message_timestamp == latest_timestamp
        ]
        age_seconds = time.time() - latest_timestamp
        if (
            age_seconds < -RECENT_POKE_FUTURE_TOLERANCE_SECONDS
            or age_seconds > RECENT_POKE_MAX_AGE_SECONDS
        ):
            return None, self._failure(
                "发送戳一戳失败：本会话最新消息的时间不在安全回戳范围内（只接受 120 秒内的戳一戳消息），无法确定回戳目标。",
                stage="message.get_recent",
            )

        identities = [
            self._poke_notice_identity(message, current_stream_id)
            for message in latest_messages
        ]
        if any(identity is None for identity in identities):
            return None, self._failure(
                "发送戳一戳失败：当前会话最新消息不是可确认的、发给机器人的 QQ 戳一戳通知；请提供 msg_id。",
                stage="message.get_recent",
            )

        confirmed_identities = [
            identity for identity in identities if identity is not None
        ]
        actor_user_ids = {identity[1] for identity in confirmed_identities}
        if len(actor_user_ids) != 1:
            # SnowLuma 通知时间精度为秒；同秒出现多位发起者时不能依赖数据库返回顺序。
            return None, self._failure(
                "发送戳一戳失败：同一最新时间点有多位用户戳了机器人，无法唯一确认回戳目标。",
                stage="message.get_recent",
            )

        selected_identity = sorted(
            confirmed_identities, key=lambda identity: identity[0]
        )[-1]
        return selected_identity, None

    @classmethod
    def _poke_notice_identity(
        cls, message: Mapping[str, Any], current_stream_id: str
    ) -> PokeNoticeIdentity | None:
        """验证 SnowLuma 戳一戳通知，并返回内部消息 ID 与发起者 ID。"""

        message_id = str(message.get("message_id") or "").strip()
        if not message_id.startswith(POKE_NOTICE_ID_PREFIX):
            return None
        if str(message.get("session_id") or "").strip() != current_stream_id:
            return None
        if str(message.get("platform") or "").strip().casefold() != "qq":
            return None
        if message.get("is_notify") is not True:
            return None

        message_info = message.get("message_info")
        if not isinstance(message_info, Mapping):
            return None
        user_info = message_info.get("user_info")
        additional_config = message_info.get("additional_config")
        if not isinstance(user_info, Mapping) or not isinstance(
            additional_config, Mapping
        ):
            return None
        if str(additional_config.get("snowluma_notice_type") or "").strip() != "notify":
            return None
        if (
            str(additional_config.get("snowluma_notice_sub_type") or "").strip()
            != "poke"
        ):
            return None

        actor_user_id = cls._qq_id(user_info.get("user_id"))
        target_id = cls._qq_id(additional_config.get("target_id"))
        self_id = cls._qq_id(additional_config.get("self_id"))
        if (
            actor_user_id is None
            or target_id is None
            or self_id is None
            or target_id != self_id
            or actor_user_id == self_id
        ):
            return None
        return message_id, actor_user_id

    @staticmethod
    def _timestamp(value: Any) -> float | None:
        """解析 Host 消息时间戳，只接受有限的正数。"""

        try:
            timestamp = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(timestamp) or timestamp <= 0:
            return None
        return timestamp

    @staticmethod
    def _host_error(result: Any) -> str | None:
        """提取 Host 能力调用错误，避免与 SnowLuma 业务结果混淆。"""

        if not isinstance(result, Mapping) or result.get("success") is not False:
            return None
        return str(
            result.get("error") or result.get("message") or "Host 返回失败但未提供原因"
        ).strip()

    @staticmethod
    def _qq_id(value: Any) -> str | None:
        """返回有效的十进制正数 QQ 标识；无效时返回 ``None``。"""

        normalized = str(value or "").strip()
        if (
            not normalized.isascii()
            or not normalized.isdecimal()
            or not normalized.strip("0")
        ):
            return None
        return normalized

    @staticmethod
    def _failure(content: str, **details: Any) -> dict[str, Any]:
        """构造模型可读的结构化失败结果。"""

        return {
            "success": False,
            "content": content,
            "error": content,
            **details,
        }


def create_plugin() -> PokePlugin:
    """为 MaiBot Runner 创建插件实例。"""

    return PokePlugin()
