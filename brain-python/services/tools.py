import logging

from schemas import ToolCallRequest, ToolDefinition, ToolResult
from modules.base import ModuleContext
from modules.registry import _module_group_allowed
from modules.remote import RemoteModuleService, module_services_from_env


logger = logging.getLogger(__name__)

_ECHO_TOOL = ToolDefinition(
    name="echo",
    description="Fake tool that returns the provided text.",
    input_schema={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text to echo back.",
            },
        },
        "required": ["text"],
    },
)


def list_tools() -> list[ToolDefinition]:
    return [_ECHO_TOOL, *list_remote_tools()]


def list_remote_tools() -> list[ToolDefinition]:
    tools = []
    seen = {_ECHO_TOOL.name}
    for service in module_services_from_env():
        for tool in service.list_tools():
            if tool.name in seen:
                logger.warning("ignoring duplicate remote tool %s from module %s", tool.name, service.name)
                continue
            seen.add(tool.name)
            tools.append(tool)
    return tools


def call_tool(request: ToolCallRequest, context: ModuleContext | None = None) -> ToolResult:
    request = _request_with_context(request, context)
    if request.name == _ECHO_TOOL.name:
        text = str(request.arguments.get("text", ""))
        return ToolResult(
            tool_name=_ECHO_TOOL.name,
            ok=True,
            data={"text": text},
        )

    owner = _remote_tool_owner(request.name)
    if owner is not None:
        if not _module_group_allowed(owner.name, _context_from_request(request)):
            return ToolResult(tool_name=request.name, ok=False, error="group_policy_denied")
        return owner.call_tool(request)

    return ToolResult(
        tool_name=request.name,
        ok=False,
        error=f"unknown tool: {request.name}",
    )


def _remote_tool_owner(tool_name: str) -> RemoteModuleService | None:
    services = module_services_from_env()
    owners = {}
    for service in services:
        for tool in service.list_tools():
            owners.setdefault(tool.name, service)

    if tool_name in owners:
        return owners[tool_name]

    return None


def _request_with_context(request: ToolCallRequest, context: ModuleContext | None) -> ToolCallRequest:
    if context is None:
        return request
    updates = {
        "message_type": request.message_type or context.message_type,
        "group_id": request.group_id or context.group_id,
        "user_id": request.user_id or context.user_id,
    }
    if hasattr(request, "model_copy"):
        return request.model_copy(update=updates)
    return request.copy(update=updates)


def _context_from_request(request: ToolCallRequest) -> ModuleContext:
    return ModuleContext(
        group_id=_string_id(request.group_id),
        user_id=_string_id(request.user_id),
        message_type=request.message_type or "",
    )


def _string_id(value: str | int | None) -> str:
    if value is None:
        return ""
    return str(value).strip()
