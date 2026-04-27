from typing import Any, Protocol

from schemas import BrainResponse


ModuleArguments = dict[str, Any]
ModuleResult = dict[str, Any]


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
