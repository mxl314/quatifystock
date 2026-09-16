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
    kind: str = "bottom"


class _PivotWindow:
    """Maintain three consecutive, completed bars for a pivot detector."""

    def __init__(self, contract: str, interval_seconds: int) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds 必须大于 0")
        self.contract = contract
        self.interval_seconds = interval_seconds
        self._bars: deque[Bar] = deque(maxlen=3)
        self._last_end = None

    def update(self, bar: Bar) -> PivotSignal | None:
        if (bar.contract != self.contract
                or bar.interval_seconds != self.interval_seconds):
            return None
        if bar.end_time - bar.start_time != timedelta(seconds=self.interval_seconds):
            return None
        if self._last_end != bar.start_time:
            self._bars.clear()
        self._last_end = bar.end_time
        self._bars.append(bar)
        if len(self._bars) != 3:
            return None
        return self._match(*self._bars)

    def _match(
        self, previous: Bar, middle: Bar, confirmation: Bar,
    ) -> PivotSignal | None:
        raise NotImplementedError

    @staticmethod
    def _bottom(
        previous: Bar, middle: Bar, confirmation: Bar,
    ) -> PivotSignal | None:
        if (middle.low_price < previous.low_price
                and middle.low_price < confirmation.low_price
                and confirmation.close_price > middle.high_price):
            return PivotSignal(middle, confirmation, "bottom")
        return None

    @staticmethod
    def _top(
        previous: Bar, middle: Bar, confirmation: Bar,
    ) -> PivotSignal | None:
        if (middle.high_price > previous.high_price
                and middle.high_price > confirmation.high_price
                and confirmation.close_price < middle.low_price):
            return PivotSignal(middle, confirmation, "top")
        return None


class BottomPivot(_PivotWindow):
    """Detect confirmed bottom pivots for one contract and bar interval."""

    def _match(
        self, previous: Bar, middle: Bar, confirmation: Bar,
    ) -> PivotSignal | None:
        return self._bottom(previous, middle, confirmation)


class TopPivot(_PivotWindow):
    """Detect confirmed top pivots for one contract and bar interval."""

    def _match(
        self, previous: Bar, middle: Bar, confirmation: Bar,
    ) -> PivotSignal | None:
        return self._top(previous, middle, confirmation)


class PivotDetector(_PivotWindow):
    """Detect both confirmed bottom and top pivots."""

    def _match(
        self, previous: Bar, middle: Bar, confirmation: Bar,
    ) -> PivotSignal | None:
        return (
            self._bottom(previous, middle, confirmation)
            or self._top(previous, middle, confirmation)
        )


class FiveMinuteBottomPivot(BottomPivot):
    def __init__(self, contract: str) -> None:
        super().__init__(contract, 300)


class PivotStrategy(Strategy):
    """Buy bottom pivots and sell top pivots for any configured bar interval."""

    def __init__(
        self,
        contract: str,
        interval_seconds: int,
        *,
        volume: int = 1,
        execute: bool = False,
    ) -> None:
        super().__init__()
        self.contract = contract
        self.interval_seconds = interval_seconds
        self.volume = volume
        self.execute = execute
        self.detector = PivotDetector(contract, interval_seconds)
        self.latest_ask = 0.0
        self.latest_bid = 0.0
        self.submitted_order: str | None = None
        self.last_signal: PivotSignal | None = None

    def on_tick(self, tick: Tick) -> None:
        if tick.contract == self.contract:
            self.latest_ask = tick.ask_price if tick.ask_price > 0 else tick.last_price
            self.latest_bid = tick.bid_price if tick.bid_price > 0 else tick.last_price

    def on_bar(self, bar: Bar) -> None:
        signal = self.detector.update(bar)
        if signal is None or self.submitted_order is not None:
            return
        self.last_signal = signal
        if not self.execute:
            return
        if signal.kind == "bottom":
            price = self.latest_ask if self.latest_ask > 0 else bar.close_price
            self.submitted_order = self.buy(self.contract, price, self.volume)
        else:
            price = self.latest_bid if self.latest_bid > 0 else bar.close_price
            self.submitted_order = self.sell(self.contract, price, self.volume)


class FiveMinutePivotStrategy(PivotStrategy):
    """Backward-compatible five-minute pivot strategy alias."""

    def __init__(self, contract: str, *, volume: int = 1, execute: bool = False) -> None:
        super().__init__(contract, 300, volume=volume, execute=execute)
