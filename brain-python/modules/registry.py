from collections.abc import Iterable
from typing import Any

from schemas import BrainResponse

from modules.bilibili import BilibiliModule
from modules.base import DeterministicModule
from modules.echo import ToolEchoModule
from modules.summary import SummaryModule
from modules.weather import WeatherModule


class DeterministicModuleRegistry:
    def __init__(self, modules: Iterable[DeterministicModule] | None = None) -> None:
        self._modules = list(modules) if modules is not None else [
            ToolEchoModule(),
            WeatherModule(),
            BilibiliModule(),
            SummaryModule(),
        ]

    def resolve(self, text: str) -> DeterministicModule | None:
        for module in self._modules:
            if module.detect(text):
                return module
        return None

    def handle(self, text: str, context: Any | None = None) -> BrainResponse | None:
        module = self.resolve(text)
        if module is None:
            return None

        arguments = module.parse(text)
        if context is not None:
            arguments.setdefault("context", context)
            group_id = _context_value(context, "group_id")
            if group_id is not None:
                arguments.setdefault("group_id", group_id)
            user_id = _context_value(context, "user_id")
            if user_id is not None:
                arguments.setdefault("user_id", user_id)
            saved_message_id = _context_value(context, "saved_message_id")
            if saved_message_id is not None:
                arguments.setdefault("exclude_message_id", saved_message_id)
        result = module.call(arguments)
        return module.present(result)


default_registry = DeterministicModuleRegistry()


def _context_value(context: Any, name: str) -> Any:
    value = getattr(context, name, None)
    if value is not None:
        return value

    message = getattr(context, "message", None)
    value = getattr(message, name, None)
    if value is not None:
        return value

    messages = getattr(context, "messages", None)
    if messages:
        return getattr(messages[-1], name, None)

    return None
