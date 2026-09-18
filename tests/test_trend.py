import unittest
from datetime import datetime, timedelta, timezone

from quant_framework.core import Bar
from quant_framework.strategy import (
    AdaptiveTrendFilter,
    SwingTrendTracker,
    TradingBias,
    TrendDirection,
    TrendSource,
)


CONTRACT = "DCE|F|P|2701"


def bar(interval, n, high, low, *, close=None, gap_days=0):
    start = (
        datetime(2026, 1, 1, tzinfo=timezone.utc)
        + timedelta(seconds=interval * n)
        + timedelta(days=gap_days)
    )
    return Bar(
        CONTRACT,
        interval,
        start,
        start + timedelta(seconds=interval),
        low,
        high,
        low,
        close if close is not None else (high + low) / 2,
    )


def rising_structure(interval):
    # Confirmed highs: 110 -> 120; confirmed lows: 90 -> 100.
    values = [
        (100, 95), (110, 96), (105, 90), (104, 97),
        (115, 105), (120, 106), (116, 100), (114, 107),
    ]
    return [bar(interval, n, high, low) for n, (high, low) in enumerate(values)]


def falling_structure(interval):
    # Confirmed highs: 120 -> 110; confirmed lows: 100 -> 90.
    values = [
        (115, 108), (120, 107), (116, 100), (114, 106),
        (105, 98), (110, 97), (106, 90), (104, 96),
    ]
    return [bar(interval, n, high, low) for n, (high, low) in enumerate(values)]


class SwingTrendTrackerTests(unittest.TestCase):
    def test_rising_highs_and_lows_are_bullish(self):
        tracker = SwingTrendTracker(CONTRACT, 3600)
        for item in rising_structure(3600):
            self.assertTrue(tracker.update(item))
        self.assertTrue(tracker.ready)
        self.assertEqual(tracker.direction, TrendDirection.BULLISH)

    def test_falling_highs_and_lows_are_bearish(self):
        tracker = SwingTrendTracker(CONTRACT, 3600)
        for item in falling_structure(3600):
            tracker.update(item)
        self.assertEqual(tracker.direction, TrendDirection.BEARISH)

    def test_calendar_gap_does_not_discard_daily_structure(self):
        tracker = SwingTrendTracker(CONTRACT, 86400)
        items = rising_structure(86400)
        # Model a weekend by shifting the later completed bars forward.
        shifted = items[:3] + [bar(86400, n, item.high_price, item.low_price, gap_days=2)
                              for n, item in enumerate(items[3:], start=3)]
        for item in shifted:
            tracker.update(item)
        self.assertEqual(tracker.direction, TrendDirection.BULLISH)

    def test_duplicate_and_wrong_contract_are_ignored(self):
        tracker = SwingTrendTracker(CONTRACT, 3600)
        item = bar(3600, 0, 100, 90)
        self.assertTrue(tracker.update(item))
        self.assertFalse(tracker.update(item))
        other = Bar("OTHER", 3600, item.start_time, item.end_time, 90, 100, 90, 95)
        self.assertFalse(tracker.update(other))
        self.assertEqual(tracker.bars_seen, 1)


class AdaptiveTrendFilterTests(unittest.TestCase):
    def test_uses_hourly_trend_while_daily_data_is_short(self):
        trend_filter = AdaptiveTrendFilter(
            CONTRACT, min_daily_bars=30, min_hourly_bars=6,
        )
        for item in rising_structure(3600):
            trend_filter.update_bar(item)

        decision = trend_filter.trend
        self.assertEqual(decision.source, TrendSource.HOURLY)
        self.assertTrue(decision.ready)
        self.assertEqual(
            trend_filter.evaluate(last_price=101, session_open=100),
            TradingBias.LONG_ONLY,
        )
        self.assertEqual(
            trend_filter.evaluate(last_price=99, session_open=100),
            TradingBias.WAIT,
        )

    def test_switches_to_daily_after_warmup(self):
        trend_filter = AdaptiveTrendFilter(
            CONTRACT, min_daily_bars=8, min_hourly_bars=6,
        )
        for item in rising_structure(3600):
            trend_filter.update_bar(item)
        for item in falling_structure(86400):
            trend_filter.update_bar(item)

        decision = trend_filter.trend
        self.assertEqual(decision.source, TrendSource.DAILY)
        self.assertEqual(decision.direction, TrendDirection.BEARISH)
        self.assertEqual(
            trend_filter.evaluate(last_price=99, session_open=100),
            TradingBias.SHORT_ONLY,
        )

    def test_waits_when_selected_source_has_no_confirmed_structure(self):
        trend_filter = AdaptiveTrendFilter(
            CONTRACT, min_daily_bars=3, min_hourly_bars=3,
        )
        for n in range(3):
            trend_filter.update_bar(bar(86400, n, 100 + n, 90 + n))

        decision = trend_filter.trend
        self.assertEqual(decision.source, TrendSource.DAILY)
        self.assertFalse(decision.ready)
        self.assertEqual(
            trend_filter.evaluate(last_price=101, session_open=100),
            TradingBias.WAIT,
        )

    def test_waits_before_either_source_is_warm(self):
        trend_filter = AdaptiveTrendFilter(CONTRACT)
        self.assertEqual(trend_filter.trend.source, TrendSource.UNAVAILABLE)
        self.assertEqual(
            trend_filter.evaluate(last_price=101, session_open=100),
            TradingBias.WAIT,
        )


if __name__ == "__main__":
    unittest.main()
