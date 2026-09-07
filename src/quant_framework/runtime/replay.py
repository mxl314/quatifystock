from __future__ import annotations

from collections.abc import Callable, Iterable

from ..adapters.mock import MockGateway
from ..core.events import EventBus
from ..core.interfaces import EventSink, TradingGateway
from ..core.models import Event, Tick
from ..services.bar_builder import BarService
from ..services.execution import TradingEngine
from ..services.timeline import TimelineService
from ..strategy.base import Strategy
from ..strategy.engine import StrategyEngine


class ReplayRuntime:
    """将历史 Tick 注入与实盘相同的中间件和策略接口。"""

    def __init__(
        self,
        trading_factory: Callable[[EventSink], TradingGateway] | None = None,
        *,
        bar_intervals: tuple[int, ...] = (60,),
    ) -> None:
        self.events = EventBus()
        factory = trading_factory or (lambda sink: MockGateway(sink, auto_fill=True))
        self.trading = TradingEngine(factory, event_bus=self.events)
        self.bars = BarService(self.events, bar_intervals)
        self.timeline = TimelineService(self.events)
        self.strategies = StrategyEngine(self.events, self.trading)

    def add_strategy(self, name: str, strategy: Strategy) -> None:
        self.strategies.add(name, strategy)

    def run(self, ticks: Iterable[Tick]) -> None:
        self.trading.connect()
        self.strategies.start()
        try:
            for tick in ticks:
                self.events.publish(Event("tick", tick))
            self.bars.flush()
        finally:
            self.strategies.stop()
            self.trading.close()
