import unittest
from datetime import datetime

from quant_framework.adapters.esunny import EsunnyAdapter
from quant_framework.adapters.esunny.trading import V10NativeGateway
from quant_framework.adapters.mock import MockGateway
from quant_framework.core import Bar, Event, EventBus, Tick
from quant_framework.services import BarBuilder, TimelineService, TradingEngine
from quant_framework.strategy import Strategy, StrategyEngine


class EventBusTests(unittest.TestCase):
    def test_stop_drains_events_created_while_draining(self):
        bus = EventBus()
        received = []

        def on_source(_event):
            bus.publish(Event("derived", 2))

        bus.subscribe("source", on_source)
        bus.subscribe("derived", lambda event: received.append(event.data))
        bus.start()
        bus.publish(Event("source", 1))
        bus.stop()
        self.assertEqual(received, [2])


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

    def test_completed_bar_is_not_reopened_by_late_tick(self):
        builder = BarBuilder(60)
        builder.update(Tick(
            "DCE|F|P|2701", 100, "2026-09-07 14:00:30",
            last_volume=1, total_volume=100,
        ))
        first = builder.update(Tick(
            "DCE|F|P|2701", 101, "2026-09-07 14:01:01",
            last_volume=1, total_volume=101,
        ))
        self.assertEqual(first.close_price, 100)

        self.assertIsNone(builder.update(Tick(
            "DCE|F|P|2701", 999, "2026-09-07 14:00:59",
            last_volume=1, total_volume=100,
        )))
        second = builder.update(Tick(
            "DCE|F|P|2701", 102, "2026-09-07 14:02:01",
            last_volume=1, total_volume=102,
        ))
        self.assertEqual(
            (second.open_price, second.high_price, second.low_price, second.close_price),
            (101, 101, 101, 101),
        )
        self.assertEqual(builder.late_ticks, 1)

    def test_out_of_order_tick_inside_open_bar_does_not_change_close(self):
        builder = BarBuilder(60)
        builder.update(Tick(
            "DCE|F|P|2701", 103, "2026-09-07 14:00:30",
            last_volume=2, total_volume=100,
        ))
        builder.update(Tick(
            "DCE|F|P|2701", 99, "2026-09-07 14:00:20",
            last_volume=1, total_volume=99,
        ))
        bar = builder.update(Tick(
            "DCE|F|P|2701", 101, "2026-09-07 14:01:01",
            last_volume=1, total_volume=101,
        ))
        self.assertEqual(
            (bar.open_price, bar.high_price, bar.low_price, bar.close_price),
            (99, 103, 99, 103),
        )
        self.assertEqual(bar.volume, 2)


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
        strategies.start()
        bar = Bar("TEST", 60, __import__("datetime").datetime(2026, 1, 1),
                  __import__("datetime").datetime(2026, 1, 1, 0, 1), 1, 2, 1, 2)
        bus.publish(Event("bar", bar))
        self.assertEqual(recorder.received, [bar])

    def test_strategy_does_not_receive_initialization_events_before_start(self):
        class Recorder(Strategy):
            def __init__(self):
                super().__init__()
                self.ticks = []

            def on_tick(self, tick):
                self.ticks.append(tick)

        bus = EventBus()
        trading = TradingEngine(lambda sink: MockGateway(sink), event_bus=bus)
        strategies = StrategyEngine(bus, trading)
        recorder = Recorder()
        strategies.add("recorder", recorder)
        bus.publish(Event("tick", Tick("TEST", 1)))
        self.assertEqual(recorder.ticks, [])
        strategies.start()
        bus.publish(Event("tick", Tick("TEST", 2)))
        self.assertEqual([tick.last_price for tick in recorder.ticks], [2])

    def test_esunny_capabilities_are_declared(self):
        self.assertTrue(EsunnyAdapter.capabilities.market_data)
        self.assertTrue(EsunnyAdapter.capabilities.trading)
        self.assertFalse(EsunnyAdapter.capabilities.native_condition_order)

    def test_esunny_maps_canonical_future_to_trading_contract(self):
        self.assertEqual(
            V10NativeGateway._trading_contract("DCE|F|P|2701"), "P2701"
        )


if __name__ == "__main__":
    unittest.main()
