from dataclasses import dataclass
import os
import re
from typing import Any, Protocol

from schemas import BrainResponse


ModuleArguments = dict[str, Any]
ModuleResult = dict[str, Any]


@dataclass(frozen=True)
class ModuleContext:
    group_id: str = ""
    user_id: str = ""
    message_type: str = ""


@dataclass(frozen=True)
class CommandInvocation:
    prefix: str
    name: str
    argument: str


DEFAULT_COMMAND_PREFIXES = ("/", ".")


def command_prefixes() -> tuple[str, ...]:
    raw = os.getenv("BRAIN_COMMAND_PREFIXES", "")
    if not raw.strip():
        return DEFAULT_COMMAND_PREFIXES

    prefixes = tuple(part.strip() for part in re.split(r"[,;\s]+", raw) if part.strip())
    return prefixes or DEFAULT_COMMAND_PREFIXES


def parse_command_invocation(text: str, aliases: set[str] | tuple[str, ...] | list[str]) -> CommandInvocation | None:
    stripped = text.strip()
    if not stripped:
        return None

    normalized_aliases = {alias.lower() for alias in aliases}
    for prefix in command_prefixes():
        if not stripped.startswith(prefix):
            continue

        command, _, argument = stripped[len(prefix) :].partition(" ")
        name = command.strip().lower()
        if name in normalized_aliases:
            return CommandInvocation(prefix=prefix, name=name, argument=argument.strip())

    return None


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
