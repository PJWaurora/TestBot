from schemas import ToolCallRequest, ToolDefinition, ToolResult


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
    return [_ECHO_TOOL]


def call_tool(request: ToolCallRequest) -> ToolResult:
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
