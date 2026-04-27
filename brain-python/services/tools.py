from schemas import ToolCallRequest, ToolDefinition, ToolResult
from modules.tsperson import TOOL_NAME as TSPERSON_TOOL_NAME
from modules.tsperson import TSPersonModule


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

_TSPERSON_TOOL = ToolDefinition(
    name=TSPERSON_TOOL_NAME,
    description="Query the configured TeamSpeak ServerQuery endpoint for current online status.",
    input_schema={
        "type": "object",
        "properties": {},
    },
)


def list_tools() -> list[ToolDefinition]:
    return [_ECHO_TOOL, _TSPERSON_TOOL]


def call_tool(request: ToolCallRequest) -> ToolResult:
    if request.name == TSPERSON_TOOL_NAME:
        result = TSPersonModule().call({"action": "status"})
        return ToolResult(
            tool_name=TSPERSON_TOOL_NAME,
            ok=bool(result.get("ok", False)),
            data=result,
            error=str(result["error"]) if result.get("error") else None,
        )

    if request.name != _ECHO_TOOL.name:
        return ToolResult(
            tool_name=request.name,
            ok=False,
            error=f"unknown tool: {request.name}",
        )

    text = str(request.arguments.get("text", ""))
    return ToolResult(
        tool_name=_ECHO_TOOL.name,
        ok=True,
        data={"text": text},
    )
