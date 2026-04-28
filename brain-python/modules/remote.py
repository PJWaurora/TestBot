import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import ValidationError

from schemas import BrainResponse, ChatRequest, ToolCallRequest, ToolDefinition, ToolResult


logger = logging.getLogger(__name__)

DEFAULT_MODULE_TIMEOUT = 5.0


@dataclass(frozen=True)
class RemoteModuleService:
    name: str
    base_url: str
    timeout: float = DEFAULT_MODULE_TIMEOUT

    def handle(self, request: ChatRequest) -> BrainResponse | None:
        payload = _model_dump(request)
        try:
            response = httpx.post(
                f"{self.base_url}/handle",
                json=payload,
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            logger.warning("remote module %s handle failed: %s", self.name, exc)
            return None

        if response.status_code < 200 or response.status_code >= 300:
            logger.warning("remote module %s handle returned HTTP %s", self.name, response.status_code)
            return None

        try:
            return _model_validate(BrainResponse, response.json())
        except (ValueError, TypeError, ValidationError) as exc:
            logger.warning("remote module %s handle returned invalid JSON: %s", self.name, exc)
            return None

    def list_tools(self) -> list[ToolDefinition]:
        try:
            response = httpx.get(f"{self.base_url}/tools", timeout=self.timeout)
        except httpx.HTTPError as exc:
            logger.warning("remote module %s tools failed: %s", self.name, exc)
            return []

        if response.status_code < 200 or response.status_code >= 300:
            logger.warning("remote module %s tools returned HTTP %s", self.name, response.status_code)
            return []

        try:
            raw_tools = response.json()
            if not isinstance(raw_tools, list):
                raise TypeError("tools response is not a list")
            return [_model_validate(ToolDefinition, tool) for tool in raw_tools]
        except (ValueError, TypeError, ValidationError) as exc:
            logger.warning("remote module %s tools returned invalid JSON: %s", self.name, exc)
            return []

    def call_tool(self, request: ToolCallRequest) -> ToolResult:
        try:
            response = httpx.post(
                f"{self.base_url}/tools/call",
                json=_model_dump(request, exclude_none=True),
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            logger.warning("remote module %s tool %s failed: %s", self.name, request.name, exc)
            return _failed_tool_result(request.name, "module_unavailable")

        if response.status_code < 200 or response.status_code >= 300:
            logger.warning(
                "remote module %s tool %s returned HTTP %s",
                self.name,
                request.name,
                response.status_code,
            )
            return _failed_tool_result(request.name, f"module_http_{response.status_code}")

        try:
            return _model_validate(ToolResult, response.json())
        except (ValueError, TypeError, ValidationError) as exc:
            logger.warning("remote module %s tool %s returned invalid JSON: %s", self.name, request.name, exc)
            return _failed_tool_result(request.name, "bad_module_response")


def module_services_from_env() -> list[RemoteModuleService]:
    timeout = _module_timeout()
    services = []
    for entry in _split_services(os.getenv("BRAIN_MODULE_SERVICES", "")):
        name, separator, url = entry.partition("=")
        if not separator:
            logger.warning("ignoring malformed BRAIN_MODULE_SERVICES entry: %s", entry)
            continue

        normalized_name = name.strip()
        normalized_url = url.strip().rstrip("/")
        if not normalized_name or not normalized_url:
            logger.warning("ignoring incomplete BRAIN_MODULE_SERVICES entry: %s", entry)
            continue

        services.append(RemoteModuleService(normalized_name, normalized_url, timeout))
    return services


def _split_services(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _module_timeout() -> float:
    raw = os.getenv("BRAIN_MODULE_TIMEOUT", "").strip()
    if not raw:
        return DEFAULT_MODULE_TIMEOUT

    try:
        timeout = float(raw)
    except ValueError:
        logger.warning("invalid BRAIN_MODULE_TIMEOUT=%r; using default %s", raw, DEFAULT_MODULE_TIMEOUT)
        return DEFAULT_MODULE_TIMEOUT

    return timeout if timeout > 0 else DEFAULT_MODULE_TIMEOUT


def _model_dump(model: Any, *, exclude_none: bool = False) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_none=exclude_none)
    return model.dict(exclude_none=exclude_none)


def _model_validate(model_type: Any, value: Any) -> Any:
    if hasattr(model_type, "model_validate"):
        return model_type.model_validate(value)
    return model_type.parse_obj(value)


def _failed_tool_result(tool_name: str, error: str) -> ToolResult:
    return ToolResult(tool_name=tool_name, ok=False, error=error)
