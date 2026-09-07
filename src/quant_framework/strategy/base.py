from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.models import Bar, Order, Tick, TimelinePoint, Trade

if TYPE_CHECKING:
    from ..services.execution import TradingEngine


class Strategy:
    """与具体柜台无关的策略基类。"""

    def __init__(self) -> None:
        self.engine: TradingEngine | None = None

    def bind(self, engine: TradingEngine) -> None:
        self.engine = engine

    def on_start(self) -> None: ...
    def on_stop(self) -> None: ...
    def on_tick(self, tick: Tick) -> None: ...
    def on_bar(self, bar: Bar) -> None: ...
    def on_timeline(self, point: TimelinePoint) -> None: ...
    def on_order(self, order: Order | dict) -> None: ...
    def on_trade(self, trade: Trade | dict) -> None: ...

    def buy(self, contract: str, price: float, volume: int, **kwargs) -> str:
        return self._engine().buy(contract, price, volume, **kwargs)

    def sell(self, contract: str, price: float, volume: int, **kwargs) -> str:
        return self._engine().sell(contract, price, volume, **kwargs)

    def close_long(self, contract: str, price: float, volume: int, **kwargs) -> str:
        return self._engine().close_long(contract, price, volume, **kwargs)

    def close_short(self, contract: str, price: float, volume: int, **kwargs) -> str:
        return self._engine().close_short(contract, price, volume, **kwargs)

    def _engine(self) -> TradingEngine:
        if self.engine is None:
            raise RuntimeError("策略尚未绑定交易引擎")
        return self.engine
