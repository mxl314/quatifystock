from __future__ import annotations

from ..core.events import EventBus
from ..core.models import Event
from ..services.execution import TradingEngine
from .base import Strategy


class StrategyEngine:
    def __init__(self, event_bus: EventBus, trading_engine: TradingEngine) -> None:
        self.events = event_bus
        self.trading = trading_engine
        self.strategies: dict[str, Strategy] = {}
        self._running = False
        for event_type in ("tick", "bar", "timeline", "order", "trade"):
            event_bus.subscribe(event_type, self._dispatch)

    def add(self, name: str, strategy: Strategy) -> None:
        if name in self.strategies:
            raise ValueError(f"策略名称重复: {name}")
        strategy.bind(self.trading)
        self.strategies[name] = strategy

    def start(self) -> None:
        self._running = True
        for strategy in tuple(self.strategies.values()):
            strategy.on_start()

    def stop(self) -> None:
        self._running = False
        for strategy in tuple(self.strategies.values()):
            strategy.on_stop()

    def _dispatch(self, event: Event) -> None:
        if not self._running:
            return
        method = f"on_{event.type}"
        for strategy in tuple(self.strategies.values()):
            getattr(strategy, method)(event.data)
