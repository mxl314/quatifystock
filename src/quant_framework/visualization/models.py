from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ChartBar:
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    open_interest: int
    complete: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TradeMarker:
    time: str
    price: float
    side: str
    offset: str = ""
    volume: int = 0
    label: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PivotMarker:
    time: str
    price: float
    confirmation_time: str
    kind: str = "bottom"
    label: str = "底部拐点"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ChartData:
    contract: str
    trading_day: str
    interval_seconds: int
    bars: tuple[ChartBar, ...]
    trades: tuple[TradeMarker, ...] = ()
    pivots: tuple[PivotMarker, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract,
            "trading_day": self.trading_day,
            "interval_seconds": self.interval_seconds,
            "bars": [bar.as_dict() for bar in self.bars],
            "trades": [trade.as_dict() for trade in self.trades],
            "pivots": [pivot.as_dict() for pivot in self.pivots],
        }
