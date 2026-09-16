import unittest
from datetime import datetime, timedelta, timezone

from quant_framework.core.models import Bar
from quant_framework.strategy.pivot import FiveMinuteBottomPivot
from quant_framework.strategy.pivot import FiveMinutePivotStrategy
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


if __name__ == "__main__":
    unittest.main()
