import unittest
from datetime import datetime

from quant_framework.adapters.esunny import EsunnyAdapter
from quant_framework.adapters.mock import MockGateway
from quant_framework.core import Bar, Event, EventBus, Tick
from quant_framework.services import BarBuilder, TimelineService, TradingEngine
from quant_framework.strategy import Strategy, StrategyEngine


class BarBuilderTests(unittest.TestCase):
    def test_tick_builds_one_minute_bar(self):
        builder = BarBuilder(60)
        self.assertIsNone(builder.update(Tick(
            "DCE|F|P|2701", 100, "2026-09-07 14:00:01", last_volume=2,
            total_volume=100, open_interest=10,
        )))
        self.assertIsNone(builder.update(Tick(
            "DCE|F|P|2701", 103, "2026-09-07 14:00:30", last_volume=3,
            total_volume=103, open_interest=12,
        )))
        bar = builder.update(Tick(
            "DCE|F|P|2701", 101, "2026-09-07 14:01:00", last_volume=1,
            total_volume=104, open_interest=11,
        ))
        self.assertIsNotNone(bar)
        self.assertEqual((bar.open_price, bar.high_price, bar.low_price, bar.close_price), (100, 103, 100, 103))
        self.assertEqual(bar.volume, 5)


class TimelineTests(unittest.TestCase):
    def test_timeline_uses_incremental_volume(self):
        bus = EventBus()
        points = []
        TimelineService(bus)
        bus.subscribe("timeline", lambda event: points.append(event.data))
        bus.publish(Event("tick", Tick("TEST", 100, "2026-09-07 09:00:00", last_volume=2, total_volume=10)))
        bus.publish(Event("tick", Tick("TEST", 110, "2026-09-07 09:00:01", last_volume=1, total_volume=11)))
        self.assertEqual(points[-1].volume, 3)
        self.assertAlmostEqual(points[-1].average_price, (100 * 2 + 110) / 3)


class StrategyTests(unittest.TestCase):
    def test_strategy_receives_canonical_bar(self):
        class Recorder(Strategy):
            def __init__(self):
                super().__init__()
                self.received = []

            def on_bar(self, bar):
                self.received.append(bar)

        bus = EventBus()
        trading = TradingEngine(lambda sink: MockGateway(sink), event_bus=bus)
        strategies = StrategyEngine(bus, trading)
        recorder = Recorder()
        strategies.add("recorder", recorder)
        bar = Bar("TEST", 60, __import__("datetime").datetime(2026, 1, 1),
                  __import__("datetime").datetime(2026, 1, 1, 0, 1), 1, 2, 1, 2)
        bus.publish(Event("bar", bar))
        self.assertEqual(recorder.received, [bar])

    def test_esunny_capabilities_are_declared(self):
        self.assertTrue(EsunnyAdapter.capabilities.market_data)
        self.assertTrue(EsunnyAdapter.capabilities.trading)
        self.assertFalse(EsunnyAdapter.capabilities.native_condition_order)


if __name__ == "__main__":
    unittest.main()
