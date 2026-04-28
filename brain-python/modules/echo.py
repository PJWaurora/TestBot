from schemas import BrainMessage, BrainResponse

from modules.base import ModuleArguments, ModuleResult, parse_command_invocation


class ToolEchoModule:
    name = "tool_echo"
    command_aliases = ("tool-echo",)

    def detect(self, text: str) -> bool:
        return parse_command_invocation(text, self.command_aliases) is not None

    def parse(self, text: str) -> ModuleArguments:
        invocation = parse_command_invocation(text, self.command_aliases)
        return {"text": invocation.argument if invocation is not None else ""}

    def call(self, arguments: ModuleArguments) -> ModuleResult:
        return {"text": str(arguments.get("text", ""))}

    def present(self, result: ModuleResult) -> BrainResponse:
        reply = str(result.get("text", ""))
        return BrainResponse(
            handled=True,
            reply=reply,
            should_reply=bool(reply),
            messages=[BrainMessage(type="text", text=reply)] if reply else [],
        )
