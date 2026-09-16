from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import timedelta

from ..core.models import Bar, Tick
from .base import Strategy


@dataclass(frozen=True, slots=True)
class PivotSignal:
    pivot: Bar
    confirmation: Bar


class FiveMinuteBottomPivot:
    """三根连续完整 K 线：中间低点更低，后一根收盘突破中间高点。"""

    def __init__(self, contract: str) -> None:
        self.contract = contract
        self._bars: deque[Bar] = deque(maxlen=3)
        self._last_end = None

    def update(self, bar: Bar) -> PivotSignal | None:
        if bar.contract != self.contract or bar.interval_seconds != 300:
            return None
        if bar.end_time - bar.start_time != timedelta(minutes=5):
            return None
        if self._last_end != bar.start_time:
            self._bars.clear()
        self._last_end = bar.end_time
        self._bars.append(bar)
        if len(self._bars) != 3:
            return None
        previous, middle, confirmation = self._bars
        if (middle.low_price < previous.low_price
                and middle.low_price < confirmation.low_price
                and confirmation.close_price > middle.high_price):
            return PivotSignal(middle, confirmation)
        return None


class FiveMinutePivotStrategy(Strategy):
    """Gateway-neutral, one-shot bottom-pivot buy strategy."""

    def __init__(self, contract: str, *, volume: int = 1, execute: bool = False) -> None:
        super().__init__()
        self.contract = contract
        self.volume = volume
        self.execute = execute
        self.detector = FiveMinuteBottomPivot(contract)
        self.latest_ask = 0.0
        self.submitted_order: str | None = None
        self.last_signal: PivotSignal | None = None

    def on_tick(self, tick: Tick) -> None:
        if tick.contract == self.contract:
            self.latest_ask = tick.ask_price if tick.ask_price > 0 else tick.last_price

    def on_bar(self, bar: Bar) -> None:
        signal = self.detector.update(bar)
        if signal is None or self.submitted_order is not None:
            return
        self.last_signal = signal
        if not self.execute:
            return
        price = self.latest_ask if self.latest_ask > 0 else bar.close_price
        self.submitted_order = self.buy(self.contract, price, self.volume)
