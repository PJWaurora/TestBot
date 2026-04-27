from collections.abc import Iterable

from schemas import BrainResponse

from modules.bilibili import BilibiliModule
from modules.base import DeterministicModule
from modules.echo import ToolEchoModule
from modules.weather import WeatherModule


class DeterministicModuleRegistry:
    def __init__(self, modules: Iterable[DeterministicModule] | None = None) -> None:
        self._modules = list(modules) if modules is not None else [
            ToolEchoModule(),
            WeatherModule(),
            BilibiliModule(),
        ]

    def resolve(self, text: str) -> DeterministicModule | None:
        for module in self._modules:
            if module.detect(text):
                return module
        return None

    def handle(self, text: str) -> BrainResponse | None:
        module = self.resolve(text)
        if module is None:
            return None

        arguments = module.parse(text)
        result = module.call(arguments)
        return module.present(result)


default_registry = DeterministicModuleRegistry()
