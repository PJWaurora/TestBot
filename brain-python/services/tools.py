import logging

from schemas import ToolCallRequest, ToolDefinition, ToolResult
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


def call_tool(request: ToolCallRequest) -> ToolResult:
    if request.name == _ECHO_TOOL.name:
        text = str(request.arguments.get("text", ""))
        return ToolResult(
            tool_name=_ECHO_TOOL.name,
            ok=True,
            data={"text": text},
        )

    owner = _remote_tool_owner(request.name)
    if owner is not None:
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
