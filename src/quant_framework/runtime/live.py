from __future__ import annotations

import threading
from collections.abc import Callable

from ..core.events import EventBus
from ..core.interfaces import EventSink, MarketDataGateway, TradingGateway
from ..services.bar_builder import BarService
from ..services.execution import TradingEngine
from ..services.order_storage import OrderStorageService
from ..services.timeline import TimelineService
from ..services.tick_storage import TickStorageService
from ..storage import SQLiteOrderStore, SQLiteTickStore
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
        tick_store: SQLiteTickStore | None = None,
        tick_flush_seconds: float = 60,
        order_store: SQLiteOrderStore | None = None,
        gateway_name: str = "",
        account: str = "",
        trading_day: str = "",
    ) -> None:
        self.events = EventBus()
        self._trading_ready = threading.Event()
        self._trading_error: object | None = None
        self._strategies_started = False
        self.events.subscribe("gateway.ready", lambda _event: self._trading_ready.set())
        self.events.subscribe("gateway.error", self._on_gateway_error)
        self.events.subscribe("gateway.login", self._on_gateway_login)
        self.trading = TradingEngine(trading_factory, event_bus=self.events)
        self.market = QuoteClient(market_factory, event_bus=self.events)
        self.bars = BarService(self.events, bar_intervals)
        self.timeline = TimelineService(self.events)
        self.tick_storage = (
            TickStorageService(self.events, tick_store, flush_seconds=tick_flush_seconds)
            if tick_store is not None else None
        )
        self.order_storage = (
            OrderStorageService(
                self.events, order_store, gateway=gateway_name,
                account=account, trading_day=trading_day,
            )
            if order_store is not None else None
        )
        self.strategies = StrategyEngine(self.events, self.trading)

    def add_strategy(self, name: str, strategy: Strategy) -> None:
        self.strategies.add(name, strategy)

    def connect(self, timeout: float = 30) -> None:
        self.events.start()
        if self.tick_storage:
            self.tick_storage.start()
        if self.order_storage:
            self.order_storage.start()
        self.trading.connect()
        if not self._trading_ready.wait(timeout):
            raise TimeoutError("等待交易 API Ready 超时")
        if self._trading_error is not None:
            raise RuntimeError(f"交易网关连接失败: {self._trading_error}")
        self.market.connect(timeout)
        self.strategies.start()
        self._strategies_started = True

    def subscribe(self, contract: str) -> None:
        self.market.subscribe(contract)

    def close(self) -> None:
        if self._strategies_started:
            self.strategies.stop()
            self._strategies_started = False
        self.market.gateway.close()
        self.trading.gateway.close()
        self.bars.flush()
        self.events.stop()
        try:
            if self.tick_storage:
                self.tick_storage.close()
        finally:
            if self.order_storage:
                self.order_storage.close()

    def _on_gateway_error(self, event) -> None:
        if not self._trading_ready.is_set():
            self._trading_error = event.data
            self._trading_ready.set()

    def _on_gateway_login(self, event) -> None:
        data = event.data
        if (not self._trading_ready.is_set() and isinstance(data, dict)
                and int(data.get("error_code", 0)) != 0):
            self._trading_error = data
            self._trading_ready.set()
