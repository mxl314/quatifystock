from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum

from ..core.models import Bar


class TrendDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class TrendSource(str, Enum):
    DAILY = "daily"
    HOURLY = "hourly"
    UNAVAILABLE = "unavailable"


class TradingBias(str, Enum):
    LONG_ONLY = "long_only"
    SHORT_ONLY = "short_only"
    WAIT = "wait"


@dataclass(frozen=True, slots=True)
class TrendDecision:
    direction: TrendDirection
    source: TrendSource
    ready: bool
    bars_seen: int
    reason: str


class SwingTrendTracker:
    """Track a trend from confirmed swing highs and lows.

    A swing is confirmed only after the following completed bar arrives. Calendar
    gaps are allowed so the same implementation works for futures night sessions,
    weekends and daily bars. Duplicate or out-of-order bars are ignored.
    """

    def __init__(self, contract: str, interval_seconds: int) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds 必须大于 0")
        self.contract = contract
        self.interval_seconds = interval_seconds
        self._bars: deque[Bar] = deque(maxlen=3)
        self._highs: deque[float] = deque(maxlen=2)
        self._lows: deque[float] = deque(maxlen=2)
        self._last_end = None
        self.bars_seen = 0

    @property
    def ready(self) -> bool:
        return len(self._highs) == 2 and len(self._lows) == 2

    @property
    def direction(self) -> TrendDirection:
        if not self.ready:
            return TrendDirection.NEUTRAL
        highs_rising = self._highs[1] > self._highs[0]
        lows_rising = self._lows[1] > self._lows[0]
        highs_falling = self._highs[1] < self._highs[0]
        lows_falling = self._lows[1] < self._lows[0]
        if highs_rising and lows_rising:
            return TrendDirection.BULLISH
        if highs_falling and lows_falling:
            return TrendDirection.BEARISH
        return TrendDirection.NEUTRAL

    def update(self, bar: Bar) -> bool:
        if bar.contract != self.contract or bar.interval_seconds != self.interval_seconds:
            return False
        if bar.end_time <= bar.start_time:
            return False
        if self._last_end is not None and bar.end_time <= self._last_end:
            return False

        self._last_end = bar.end_time
        self.bars_seen += 1
        self._bars.append(bar)
        if len(self._bars) != 3:
            return True

        previous, middle, confirmation = self._bars
        if (middle.high_price > previous.high_price
                and middle.high_price > confirmation.high_price):
            self._highs.append(middle.high_price)
        if (middle.low_price < previous.low_price
                and middle.low_price < confirmation.low_price):
            self._lows.append(middle.low_price)
        return True


class AdaptiveTrendFilter:
    """Prefer daily trend and fall back to 60-minute trend while warming up."""

    def __init__(
        self,
        contract: str,
        *,
        min_daily_bars: int = 30,
        min_hourly_bars: int = 6,
        daily_interval_seconds: int = 86_400,
        hourly_interval_seconds: int = 3_600,
    ) -> None:
        if min_daily_bars <= 0:
            raise ValueError("min_daily_bars 必须大于 0")
        if min_hourly_bars <= 0:
            raise ValueError("min_hourly_bars 必须大于 0")
        self.contract = contract
        self.min_daily_bars = min_daily_bars
        self.min_hourly_bars = min_hourly_bars
        self.daily = SwingTrendTracker(contract, daily_interval_seconds)
        self.hourly = SwingTrendTracker(contract, hourly_interval_seconds)

    def update_bar(self, bar: Bar) -> bool:
        """Consume a completed daily or hourly bar; return whether it was used."""
        return self.daily.update(bar) or self.hourly.update(bar)

    @property
    def trend(self) -> TrendDecision:
        if self.daily.bars_seen >= self.min_daily_bars:
            return self._decision(self.daily, TrendSource.DAILY)
        if self.hourly.bars_seen >= self.min_hourly_bars:
            return self._decision(self.hourly, TrendSource.HOURLY)
        return TrendDecision(
            TrendDirection.NEUTRAL,
            TrendSource.UNAVAILABLE,
            False,
            max(self.daily.bars_seen, self.hourly.bars_seen),
            "日线与60分钟数据均未完成预热",
        )

    def evaluate(self, last_price: float, session_open: float) -> TradingBias:
        """Combine the selected trend with the current session opening price."""
        decision = self.trend
        if not decision.ready or last_price <= 0 or session_open <= 0:
            return TradingBias.WAIT
        if (decision.direction is TrendDirection.BULLISH
                and last_price > session_open):
            return TradingBias.LONG_ONLY
        if (decision.direction is TrendDirection.BEARISH
                and last_price < session_open):
            return TradingBias.SHORT_ONLY
        return TradingBias.WAIT

    @staticmethod
    def _decision(
        tracker: SwingTrendTracker,
        source: TrendSource,
    ) -> TrendDecision:
        if not tracker.ready:
            return TrendDecision(
                TrendDirection.NEUTRAL,
                source,
                False,
                tracker.bars_seen,
                "尚未形成两组已确认的高低点",
            )
        return TrendDecision(
            tracker.direction,
            source,
            True,
            tracker.bars_seen,
            "趋势结构已就绪",
        )
