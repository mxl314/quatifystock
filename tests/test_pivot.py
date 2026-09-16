import unittest
from datetime import datetime, timedelta, timezone

from quant_framework.core.models import Bar
from quant_framework.strategy.pivot import (
    BottomPivot,
    FiveMinuteBottomPivot,
    FiveMinutePivotStrategy,
    PivotDetector,
    PivotStrategy,
)
from quant_framework.adapters.mock import MockGateway
from quant_framework.core.events import EventBus
from quant_framework.services.execution import TradingEngine


class PivotTests(unittest.TestCase):
    def bar(self, n, high, low, close, *, start=None):
        start = start or datetime(2026, 9, 15, 13, 0, tzinfo=timezone.utc) + timedelta(minutes=5 * n)
        return Bar("DCE|F|P|2701", 300, start, start + timedelta(minutes=5),
                   close, high, low, close)

    def test_confirmed_bottom(self):
        detector = FiveMinuteBottomPivot("DCE|F|P|2701")
        self.assertIsNone(detector.update(self.bar(0, 101, 98, 99)))
        self.assertIsNone(detector.update(self.bar(1, 100, 95, 96)))
        signal = detector.update(self.bar(2, 103, 97, 102))
        self.assertIsNotNone(signal)
        self.assertEqual(signal.pivot.low_price, 95)

    def test_same_pattern_works_on_one_minute_bars(self):
        detector = BottomPivot("DCE|F|P|2701", 60)
        start = datetime(2026, 9, 15, 13, 0, tzinfo=timezone.utc)

        def one_minute(n, high, low, close):
            bar_start = start + timedelta(minutes=n)
            return Bar(
                "DCE|F|P|2701", 60, bar_start,
                bar_start + timedelta(minutes=1), close, high, low, close,
            )

        self.assertIsNone(detector.update(one_minute(0, 101, 98, 99)))
        self.assertIsNone(detector.update(one_minute(1, 100, 95, 96)))
        signal = detector.update(one_minute(2, 103, 97, 102))
        self.assertIsNotNone(signal)
        self.assertEqual(signal.pivot.low_price, 95)

    def test_confirmed_top(self):
        detector = PivotDetector("DCE|F|P|2701", 300)
        self.assertIsNone(detector.update(self.bar(0, 101, 98, 100)))
        self.assertIsNone(detector.update(self.bar(1, 105, 99, 104)))
        signal = detector.update(self.bar(2, 103, 96, 98))
        self.assertIsNotNone(signal)
        self.assertEqual(signal.kind, "top")
        self.assertEqual(signal.pivot.high_price, 105)

    def test_gap_and_unconfirmed_bar_do_not_signal(self):
        detector = FiveMinuteBottomPivot("DCE|F|P|2701")
        detector.update(self.bar(0, 101, 98, 99))
        detector.update(self.bar(1, 100, 95, 96))
        self.assertIsNone(detector.update(self.bar(2, 103, 97, 102,
                                               start=datetime(2026, 9, 15, 13, 20, tzinfo=timezone.utc))))
        detector = FiveMinuteBottomPivot("DCE|F|P|2701")
        detector.update(self.bar(0, 101, 98, 99))
        detector.update(self.bar(1, 100, 95, 96))
        self.assertIsNone(detector.update(self.bar(2, 103, 97, 100)))

    def test_strategy_order_uses_canonical_contract_through_engine(self):
        bus = EventBus()
        engine = TradingEngine(lambda sink: MockGateway(sink), event_bus=bus)
        engine.connect()
        strategy = FiveMinutePivotStrategy("DCE|F|P|2701", execute=True)
        strategy.bind(engine)
        strategy.on_tick(__import__("quant_framework").Tick(
            "DCE|F|P|2701", 102, ask_price=103,
        ))
        strategy.on_bar(self.bar(0, 101, 98, 99))
        strategy.on_bar(self.bar(1, 100, 95, 96))
        strategy.on_bar(self.bar(2, 103, 97, 102))
        self.assertIsNotNone(strategy.submitted_order)
        order = engine.orders[strategy.submitted_order]
        self.assertEqual(order.request.contract, "DCE|F|P|2701")
        self.assertEqual(order.request.price, 103)
        engine.close()

    def test_top_pivot_strategy_sells_at_latest_bid(self):
        bus = EventBus()
        engine = TradingEngine(lambda sink: MockGateway(sink), event_bus=bus)
        engine.connect()
        strategy = PivotStrategy("DCE|F|P|2701", 300, execute=True)
        strategy.bind(engine)
        strategy.on_tick(__import__("quant_framework").Tick(
            "DCE|F|P|2701", 102, bid_price=101,
        ))
        strategy.on_bar(self.bar(0, 101, 98, 100))
        strategy.on_bar(self.bar(1, 105, 99, 104))
        strategy.on_bar(self.bar(2, 103, 96, 98))
        self.assertIsNotNone(strategy.submitted_order)
        order = engine.orders[strategy.submitted_order]
        self.assertEqual(order.request.side.value, "S")
        self.assertEqual(order.request.price, 101)
        engine.close()


if __name__ == "__main__":
    unittest.main()
