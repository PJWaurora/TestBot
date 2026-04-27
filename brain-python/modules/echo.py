from schemas import BrainMessage, BrainResponse

from modules.base import ModuleArguments, ModuleResult


class ToolEchoModule:
    name = "tool_echo"
    command = "/tool-echo"

    def detect(self, text: str) -> bool:
        command, _, _ = text.partition(" ")
        return command.lower() == self.command

    def parse(self, text: str) -> ModuleArguments:
        _, _, argument = text.partition(" ")
        return {"text": argument.strip()}

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
