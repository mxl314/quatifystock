from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from ..core.enums import OrderStatus
from ..core.models import Bar, Order, Tick
from .base import Strategy
from .pivot import PivotDetector, PivotSignal
from .trend import AdaptiveTrendFilter, TradingBias


@dataclass(frozen=True, slots=True)
class EntrySetup:
    side: str
    trigger_price: float
    stop_price: float
    atr: float


class FuturesTrendStrategy(Strategy):
    """CTP-compatible intraday futures strategy.

    Direction comes from daily swings, falling back to 60-minute swings during
    daily warm-up. Three-minute L-H-L / H-L-H structures arm entries, which are
    triggered from ticks. Orders still travel through TradingEngine so gateway
    routing and risk checks remain centralized.
    """

    def __init__(
        self,
        contract: str,
        *,
        volume: int = 1,
        execute: bool = False,
        entry_interval_seconds: int = 180,
        atr_period: int = 14,
        entry_atr: float = 0.2,
        stop_atr: float = 0.15,
        min_daily_bars: int = 30,
        min_hourly_bars: int = 6,
    ) -> None:
        super().__init__()
        if volume <= 0:
            raise ValueError("volume 必须大于 0")
        if atr_period <= 0:
            raise ValueError("atr_period 必须大于 0")
        if entry_atr <= 0 or stop_atr < 0:
            raise ValueError("ATR 入场与止损参数无效")
        self.contract = contract
        self.volume = volume
        self.execute = execute
        self.entry_interval_seconds = entry_interval_seconds
        self.atr_period = atr_period
        self.entry_atr = entry_atr
        self.stop_atr = stop_atr
        self.trend_filter = AdaptiveTrendFilter(
            contract,
            min_daily_bars=min_daily_bars,
            min_hourly_bars=min_hourly_bars,
        )
        self.detector = PivotDetector(contract, entry_interval_seconds)
        self._pivots: deque[PivotSignal] = deque(maxlen=3)
        self._true_ranges: deque[float] = deque(maxlen=atr_period)
        self._previous_close: float | None = None
        self.session_open = 0.0
        self.latest_ask = 0.0
        self.latest_bid = 0.0
        self.setup: EntrySetup | None = None
        self.last_signal: EntrySetup | None = None
        self.entry_order: str | None = None
        self.exit_order: str | None = None
        self.position_side = "flat"
        self.position_volume = 0
        self._pending_entry_side: str | None = None
        self._exit_start_volume = 0

    @property
    def atr(self) -> float | None:
        if len(self._true_ranges) < self.atr_period:
            return None
        return sum(self._true_ranges) / len(self._true_ranges)

    @property
    def bias(self) -> TradingBias:
        price = self.latest_ask or self.latest_bid
        return self.trend_filter.evaluate(price, self.session_open)

    def on_tick(self, tick: Tick) -> None:
        if tick.contract != self.contract or tick.last_price <= 0:
            return
        self.latest_ask = tick.ask_price if tick.ask_price > 0 else tick.last_price
        self.latest_bid = tick.bid_price if tick.bid_price > 0 else tick.last_price
        if tick.open_price > 0:
            self.session_open = tick.open_price

        if self.position_side == "long" and self.setup is not None:
            if tick.last_price <= self.setup.stop_price and self.exit_order is None:
                self._submit_exit(self.latest_bid)
            return
        if self.position_side == "short" and self.setup is not None:
            if tick.last_price >= self.setup.stop_price and self.exit_order is None:
                self._submit_exit(self.latest_ask)
            return
        if self.position_side != "flat" or self.entry_order is not None:
            return

        setup = self.setup
        if setup is None:
            return
        current_bias = self.trend_filter.evaluate(tick.last_price, self.session_open)
        if (setup.side == "long" and current_bias is TradingBias.LONG_ONLY
                and tick.last_price >= setup.trigger_price):
            self._submit_entry("long", self.latest_ask)
        elif (setup.side == "short" and current_bias is TradingBias.SHORT_ONLY
                and tick.last_price <= setup.trigger_price):
            self._submit_entry("short", self.latest_bid)

    def on_bar(self, bar: Bar) -> None:
        if bar.contract != self.contract:
            return
        self.trend_filter.update_bar(bar)
        if bar.interval_seconds != self.entry_interval_seconds:
            return
        self._update_atr(bar)
        signal = self.detector.update(bar)
        if signal is not None:
            self._handle_pivot(signal)

    def on_order(self, _order: Order | dict) -> None:
        self._sync_order_state()

    def _update_atr(self, bar: Bar) -> None:
        previous = self._previous_close
        true_range = bar.high_price - bar.low_price
        if previous is not None:
            true_range = max(
                true_range,
                abs(bar.high_price - previous),
                abs(bar.low_price - previous),
            )
        self._true_ranges.append(true_range)
        self._previous_close = bar.close_price

    def _handle_pivot(self, signal: PivotSignal) -> None:
        if self.position_side != "flat" or self.entry_order is not None:
            return
        self._pivots.append(signal)
        current_atr = self.atr
        if len(self._pivots) != 3 or current_atr is None:
            return
        first, middle, last = self._pivots
        kinds = (first.kind, middle.kind, last.kind)
        if kinds == ("bottom", "top", "bottom"):
            l1 = first.pivot.low_price
            l2 = last.pivot.low_price
            if l2 > l1:
                self.setup = EntrySetup(
                    "long",
                    l2 + self.entry_atr * current_atr,
                    l2 - self.stop_atr * current_atr,
                    current_atr,
                )
        elif kinds == ("top", "bottom", "top"):
            h1 = first.pivot.high_price
            h2 = last.pivot.high_price
            if h2 < h1:
                self.setup = EntrySetup(
                    "short",
                    h2 - self.entry_atr * current_atr,
                    h2 + self.stop_atr * current_atr,
                    current_atr,
                )

    def _submit_entry(self, side: str, price: float) -> None:
        setup = self.setup
        if setup is None:
            return
        self.last_signal = setup
        if not self.execute:
            self.setup = None
            return
        self._pending_entry_side = side
        order_id = (
            self.buy(self.contract, price, self.volume)
            if side == "long"
            else self.sell(self.contract, price, self.volume)
        )
        self.entry_order = order_id
        self._sync_order_state()

    def _submit_exit(self, price: float) -> None:
        if not self.execute or self.position_volume <= 0:
            return
        self._exit_start_volume = self.position_volume
        order_id = (
            self.close_long_today(self.contract, price, self.position_volume)
            if self.position_side == "long"
            else self.close_short_today(self.contract, price, self.position_volume)
        )
        self.exit_order = order_id
        self._sync_order_state()

    def _sync_order_state(self) -> None:
        if self.engine is None:
            return
        terminal = {
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
        }
        if self.entry_order is not None:
            order = self.engine.orders.get(self.entry_order)
            if order is not None and order.traded_volume > 0:
                self.position_side = self._pending_entry_side or "flat"
                self.position_volume = order.traded_volume
            if order is not None and order.status is OrderStatus.FILLED:
                self.position_volume = order.request.volume
                self.entry_order = None
                self._pending_entry_side = None
            elif order is not None and order.status in terminal:
                self.entry_order = None
                self._pending_entry_side = None
        if self.exit_order is not None:
            order = self.engine.orders.get(self.exit_order)
            if order is not None and order.traded_volume > 0:
                self.position_volume = max(
                    0, self._exit_start_volume - order.traded_volume,
                )
            if order is not None and order.status is OrderStatus.FILLED:
                self.position_side = "flat"
                self.position_volume = 0
                self.exit_order = None
                self._exit_start_volume = 0
                self.setup = None
                self._pivots.clear()
            elif order is not None and order.status in terminal:
                self.exit_order = None
                self._exit_start_volume = 0
                if self.position_volume == 0:
                    self.position_side = "flat"
                    self.setup = None
                    self._pivots.clear()
