from __future__ import annotations

from collections.abc import Callable

from ..core.events import EventBus
from ..core.interfaces import EventSink, MarketDataGateway, TradingGateway
from ..services.bar_builder import BarService
from ..services.execution import TradingEngine
from ..services.timeline import TimelineService
from ..strategy.base import Strategy
from ..strategy.engine import StrategyEngine
from .market_client import QuoteClient

MarketFactory = Callable[[EventSink], MarketDataGateway]
TradingFactory = Callable[[EventSink], TradingGateway]


class LiveRuntime:
    """组装底层适配器、中间件和策略的实盘/模拟盘运行容器。"""

    def __init__(
        self,
        market_factory: MarketFactory,
        trading_factory: TradingFactory,
        *,
        bar_intervals: tuple[int, ...] = (60,),
    ) -> None:
        self.events = EventBus()
        self.trading = TradingEngine(trading_factory, event_bus=self.events)
        self.market = QuoteClient(market_factory, event_bus=self.events)
        self.bars = BarService(self.events, bar_intervals)
        self.timeline = TimelineService(self.events)
        self.strategies = StrategyEngine(self.events, self.trading)

    def add_strategy(self, name: str, strategy: Strategy) -> None:
        self.strategies.add(name, strategy)

    def connect(self) -> None:
        self.events.start()
        self.trading.connect()
        self.market.connect()
        self.strategies.start()

    def subscribe(self, contract: str) -> None:
        self.market.subscribe(contract)

    def close(self) -> None:
        self.strategies.stop()
        self.bars.flush()
        self.market.gateway.close()
        self.trading.gateway.close()
        self.events.stop()
