from dataclasses import dataclass
from typing import Any, Protocol

from schemas import BrainResponse


ModuleArguments = dict[str, Any]
ModuleResult = dict[str, Any]


@dataclass(frozen=True)
class ModuleContext:
    group_id: str = ""
    user_id: str = ""
    message_type: str = ""


class DeterministicModule(Protocol):
    name: str

    def detect(self, text: str) -> bool:
        ...

    def parse(self, text: str) -> ModuleArguments:
        ...

    def call(self, arguments: ModuleArguments) -> ModuleResult:
        ...

    def present(self, result: ModuleResult) -> BrainResponse:
        ...
