"""Legacy in-core TSPerson module.

This module is not loaded by the default Brain registry. It is retained only
as temporary compatibility/reference code while official TSPerson behavior
lives in the external HTTP module service configured through
``BRAIN_MODULE_SERVICES`` and ``docker-compose.modules.yml``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Protocol

from schemas import BrainMessage, BrainResponse

from modules.base import ModuleArguments, ModuleResult, parse_command_invocation


TOOL_NAME = "tsperson.get_status"
HELP_TEXT = "TS 查询命令：查询人数 / 查询人类 / ts状态 / ts人数"
MISSING_CONFIG_TEXT = "TS ServerQuery 配置不完整，请设置 TS3_HOST、TS3_QUERY_USER、TS3_QUERY_PASSWORD"

TS3_IMPORT_ERROR: Exception | None = None
try:
    import ts3

    TS3_AVAILABLE = True
except Exception as exc:
    ts3 = None
    TS3_AVAILABLE = False
    TS3_IMPORT_ERROR = exc


@dataclass(frozen=True)
class ClientInfo:
    nickname: str
    channel_id: int


@dataclass(frozen=True)
class ChannelInfo:
    channel_id: int
    name: str
    total_clients: int


@dataclass(frozen=True)
class ServerStatus:
    name: str
    platform: str
    version: str
    clients_online: int
    max_clients: int
    channels_online: int
    uptime: int
    clients: list[ClientInfo]
    channels: list[ChannelInfo]


class StatusProvider(Protocol):
    def get_status(self) -> ServerStatus:
        ...


@dataclass(frozen=True)
class TS3Config:
    host: str
    query_port: int
    query_user: str
    query_password: str
    virtual_server_id: int
    timeout: float

    @classmethod
    def from_env(cls) -> "TS3Config":
        return cls(
            host=_env("TS3_HOST", "TSPERSON_HOST"),
            query_port=_int_env("TS3_QUERY_PORT", "TSPERSON_QUERY_PORT", default=10011),
            query_user=_env("TS3_QUERY_USER", "TSPERSON_QUERY_USER"),
            query_password=_env("TS3_QUERY_PASSWORD", "TSPERSON_QUERY_PASSWORD"),
            virtual_server_id=_int_env("TS3_VIRTUAL_SERVER_ID", "TSPERSON_VIRTUAL_SERVER_ID", default=1),
            timeout=_float_env("TS3_TIMEOUT", "TSPERSON_TIMEOUT", default=5.0),
        )

    def missing_fields(self) -> list[str]:
        missing = []
        if not self.host:
            missing.append("TS3_HOST")
        if not self.query_user:
            missing.append("TS3_QUERY_USER")
        if not self.query_password:
            missing.append("TS3_QUERY_PASSWORD")
        return missing


class TS3StatusProvider:
    def __init__(self, config: TS3Config | None = None) -> None:
        self.config = config or TS3Config.from_env()

    def get_status(self) -> ServerStatus:
        if not TS3_AVAILABLE:
            raise RuntimeError(f"ts3 library is not available: {TS3_IMPORT_ERROR}")

        missing = self.config.missing_fields()
        if missing:
            raise ValueError(f"missing config: {', '.join(missing)}")

        connection = ts3.query.TS3Connection()
        try:
            connection.open(self.config.host, self.config.query_port, timeout=self.config.timeout)
            connection.login(
                client_login_name=self.config.query_user,
                client_login_password=self.config.query_password,
            )
            connection.use(sid=self.config.virtual_server_id)

            server_info = _first_parsed(connection.send("serverinfo", timeout=self.config.timeout))
            clients = _parse_clients(connection.send("clientlist", timeout=self.config.timeout).parsed)
            channels = _parse_channels(connection.send("channellist", timeout=self.config.timeout).parsed)

            return ServerStatus(
                name=str(server_info.get("virtualserver_name", "Unknown")),
                platform=str(server_info.get("virtualserver_platform", "Unknown")),
                version=str(server_info.get("virtualserver_version", "Unknown")),
                clients_online=len(clients),
                max_clients=_int_value(server_info.get("virtualserver_maxclients")),
                channels_online=_int_value(server_info.get("virtualserver_channelsonline"), len(channels)),
                uptime=_int_value(server_info.get("virtualserver_uptime")),
                clients=clients,
                channels=channels,
            )
        finally:
            try:
                connection.quit()
            except Exception:
                pass


class TSPersonModule:
    name = "tsperson"

    _QUERY_PATTERN = re.compile(r"^(?:查询人数|查询人类|ts状态|ts人数|ts在线|teamspeak状态)$", re.IGNORECASE)
    _HELP_PATTERN = re.compile(r"^(?:ts帮助|tsperson帮助|teamspeak帮助)$", re.IGNORECASE)
    _COMMAND_ALIASES = (
        "ts",
        "tsperson",
        "teamspeak",
        "查询人数",
        "查询人类",
        "ts状态",
        "ts人数",
        "ts在线",
        "teamspeak状态",
        "ts帮助",
        "tsperson帮助",
        "teamspeak帮助",
    )
    _COMMAND_HELP_ARGUMENTS = {"help", "帮助", "?"}

    def __init__(self, provider: StatusProvider | None = None, config: TS3Config | None = None) -> None:
        self.provider = provider
        self.config = config

    def detect(self, text: str) -> bool:
        stripped = text.strip()
        return (
            self._HELP_PATTERN.match(stripped) is not None
            or self._QUERY_PATTERN.match(stripped) is not None
            or parse_command_invocation(stripped, self._COMMAND_ALIASES) is not None
        )

    def parse(self, text: str) -> ModuleArguments:
        stripped = text.strip()
        invocation = parse_command_invocation(stripped, self._COMMAND_ALIASES)
        if invocation is not None:
            if invocation.name.endswith("帮助") or invocation.argument.lower() in self._COMMAND_HELP_ARGUMENTS:
                return {"action": "help", "query": stripped}
            return {"action": "status", "query": stripped}

        if self._HELP_PATTERN.match(stripped):
            return {"action": "help", "query": stripped}
        return {"action": "status", "query": stripped}

    def call(self, arguments: ModuleArguments) -> ModuleResult:
        action = str(arguments.get("action", "status"))
        if action == "help":
            return {"tool_name": TOOL_NAME, "ok": True, "action": "help", "message": HELP_TEXT}

        config = self.config or TS3Config.from_env()
        missing = config.missing_fields()
        if self.provider is None and missing:
            return {
                "tool_name": TOOL_NAME,
                "ok": False,
                "action": "status",
                "error": "missing_config",
                "missing": missing,
                "message": MISSING_CONFIG_TEXT,
            }

        provider = self.provider or TS3StatusProvider(config)
        try:
            status = provider.get_status()
        except Exception as exc:
            return {
                "tool_name": TOOL_NAME,
                "ok": False,
                "action": "status",
                "error": "provider_error",
                "message": f"TS 查询失败：{exc}",
            }

        return {
            "tool_name": TOOL_NAME,
            "ok": True,
            "action": "status",
            "status": _status_dict(status),
        }

    def present(self, result: ModuleResult) -> BrainResponse:
        reply = self._reply_text(result)
        metadata = {
            "module": self.name,
            "tool_name": str(result.get("tool_name", TOOL_NAME)),
            "ok": bool(result.get("ok", False)),
        }
        if result.get("error"):
            metadata["error"] = str(result["error"])

        return BrainResponse(
            handled=True,
            reply=reply,
            should_reply=bool(reply),
            messages=[BrainMessage(type="text", text=reply)] if reply else [],
            metadata=metadata,
        )

    def _reply_text(self, result: ModuleResult) -> str:
        if result.get("action") == "help":
            return str(result.get("message") or HELP_TEXT)
        if not result.get("ok"):
            return str(result.get("message") or "TS 查询失败")

        status = result.get("status")
        if not isinstance(status, dict):
            return "TS 状态数据格式不正确"

        clients = status.get("clients") if isinstance(status.get("clients"), list) else []
        names = [
            str(client.get("nickname", "")).strip()
            for client in clients
            if isinstance(client, dict) and str(client.get("nickname", "")).strip()
        ]
        lines = [
            f"TS 服务器：{status.get('name') or 'Unknown'}",
            f"在线人数：{status.get('clients_online', 0)}/{status.get('max_clients', 0)}",
            f"频道数：{status.get('channels_online', 0)}",
            f"运行时间：{format_duration(_int_value(status.get('uptime')))}",
        ]
        if names:
            lines.append("在线用户：" + "、".join(names[:20]))
        else:
            lines.append("在线用户：无")
        return "\n".join(lines)


def format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}秒"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}分钟"
    hours = minutes // 60
    if hours < 24:
        remaining_minutes = minutes % 60
        return f"{hours}小时{remaining_minutes}分钟" if remaining_minutes else f"{hours}小时"
    days = hours // 24
    remaining_hours = hours % 24
    return f"{days}天{remaining_hours}小时" if remaining_hours else f"{days}天"


def _status_dict(status: ServerStatus) -> dict[str, Any]:
    return {
        "name": status.name,
        "platform": status.platform,
        "version": status.version,
        "clients_online": status.clients_online,
        "max_clients": status.max_clients,
        "channels_online": status.channels_online,
        "uptime": status.uptime,
        "clients": [{"nickname": client.nickname, "channel_id": client.channel_id} for client in status.clients],
        "channels": [
            {
                "channel_id": channel.channel_id,
                "name": channel.name,
                "total_clients": channel.total_clients,
            }
            for channel in status.channels
        ],
    }


def _parse_clients(raw_clients: list[dict[str, Any]]) -> list[ClientInfo]:
    clients = []
    for raw in raw_clients:
        if _int_value(raw.get("client_type")) == 1:
            continue
        clients.append(
            ClientInfo(
                nickname=str(raw.get("client_nickname", "Unknown")),
                channel_id=_int_value(raw.get("cid")),
            )
        )
    return clients


def _parse_channels(raw_channels: list[dict[str, Any]]) -> list[ChannelInfo]:
    return [
        ChannelInfo(
            channel_id=_int_value(raw.get("cid")),
            name=str(raw.get("channel_name", "Unknown")),
            total_clients=_int_value(raw.get("total_clients")),
        )
        for raw in raw_channels
    ]


def _first_parsed(response: Any) -> dict[str, Any]:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, list) and parsed:
        first = parsed[0]
        if isinstance(first, dict):
            return first
    return {}


def _env(*keys: str) -> str:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value.strip()
    return ""


def _int_env(*keys: str, default: int) -> int:
    return _int_value(_env(*keys), default)


def _float_env(*keys: str, default: float) -> float:
    value = _env(*keys)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
