from collections.abc import Iterable
import os
import re

from schemas import BrainResponse

from modules.bilibili import BilibiliModule
from modules.base import DeterministicModule, ModuleContext
from modules.echo import ToolEchoModule
from modules.tsperson import TSPersonModule


class DeterministicModuleRegistry:
    def __init__(self, modules: Iterable[DeterministicModule] | None = None) -> None:
        self._modules = list(modules) if modules is not None else [
            ToolEchoModule(),
            BilibiliModule(),
            TSPersonModule(),
        ]

    def resolve(self, text: str) -> DeterministicModule | None:
        for module in self._modules:
            if module.detect(text):
                return module
        return None

    def handle(self, text: str, context: ModuleContext | None = None) -> BrainResponse | None:
        module = self.resolve(text)
        if module is None:
            return None

        context = context or ModuleContext()
        if not _module_group_allowed(module.name, context):
            return BrainResponse(
                handled=True,
                should_reply=False,
                metadata={
                    "module": module.name,
                    "group_policy": "blocked",
                    "group_id": context.group_id,
                },
            )

        arguments = module.parse(text)
        result = module.call(arguments)
        return module.present(result)


default_registry = DeterministicModuleRegistry()


def _module_group_allowed(module_name: str, context: ModuleContext) -> bool:
    normalized = _env_module_name(module_name)
    group_id = context.group_id.strip()
    if context.message_type != "group" and not group_id:
        return True

    blocklist = _group_set(
        f"BRAIN_MODULE_{normalized}_GROUP_BLOCKLIST",
        f"{normalized}_GROUP_BLOCKLIST",
        "BRAIN_GROUP_BLOCKLIST",
    )
    if group_id and group_id in blocklist:
        return False

    allowlist = _group_set(
        f"BRAIN_MODULE_{normalized}_GROUP_ALLOWLIST",
        f"{normalized}_GROUP_ALLOWLIST",
        "BRAIN_GROUP_ALLOWLIST",
    )
    if allowlist and group_id not in allowlist:
        return False

    return True


def _group_set(*keys: str) -> set[str]:
    groups: set[str] = set()
    for key in keys:
        groups.update(_split_group_ids(os.getenv(key, "")))
    return groups


def _split_group_ids(value: str) -> set[str]:
    return {part for part in re.split(r"[\s,;]+", value.strip()) if part}


def _env_module_name(module_name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", module_name.upper()).strip("_")
