import unittest
from datetime import datetime, timedelta, timezone

from quant_framework.adapters.mock import MockGateway
from quant_framework.core import Bar, Event, EventBus, Offset, Tick
from quant_framework.services import TradingEngine
from quant_framework.strategy import (
    EntrySetup,
    FuturesTrendStrategy,
    PivotSignal,
    TradingBias,
)


CONTRACT = "DCE|F|P|2701"


class _LongTrend:
    def update_bar(self, _bar):
        return True

    def evaluate(self, _last_price, _session_open):
        return TradingBias.LONG_ONLY


class _ShortTrend(_LongTrend):
    def evaluate(self, _last_price, _session_open):
        return TradingBias.SHORT_ONLY


def pivot(kind, price, n):
    start = datetime(2026, 9, 18, 1, 0, tzinfo=timezone.utc) + timedelta(minutes=3 * n)
    if kind == "bottom":
        item = Bar(CONTRACT, 180, start, start + timedelta(minutes=3), price + 2, price + 3, price, price + 2)
    else:
        item = Bar(CONTRACT, 180, start, start + timedelta(minutes=3), price - 2, price, price - 3, price - 2)
    confirmation = Bar(
        CONTRACT, 180, item.end_time, item.end_time + timedelta(minutes=3),
        item.close_price, item.high_price, item.low_price, item.close_price,
    )
    return PivotSignal(item, confirmation, kind)


class FuturesTrendStrategyTests(unittest.TestCase):
    def engine(self):
        bus = EventBus()
        engine = TradingEngine(
            lambda sink: MockGateway(sink, auto_fill=True), event_bus=bus,
        )
        engine.connect()
        return engine

    def test_l1_h1_l2_arms_atr_entry(self):
        strategy = FuturesTrendStrategy(CONTRACT)
        strategy._true_ranges.extend([10.0] * strategy.atr_period)
        strategy._handle_pivot(pivot("bottom", 90, 0))
        strategy._handle_pivot(pivot("top", 110, 1))
        strategy._handle_pivot(pivot("bottom", 100, 2))

        self.assertEqual(strategy.setup.side, "long")
        self.assertEqual(strategy.setup.trigger_price, 102)
        self.assertEqual(strategy.setup.stop_price, 98.5)

    def test_ctp_compatible_buy_and_stop_use_trading_engine(self):
        engine = self.engine()
        strategy = FuturesTrendStrategy(CONTRACT, execute=True)
        strategy.bind(engine)
        strategy.trend_filter = _LongTrend()
        strategy.setup = EntrySetup("long", 102, 99, 10)

        strategy.on_tick(Tick(
            CONTRACT, 103, open_price=100, ask_price=104, bid_price=102,
        ))
        self.assertEqual(strategy.position_side, "long")
        entry = next(iter(engine.orders.values()))
        self.assertEqual(entry.request.offset, Offset.OPEN)
        self.assertEqual(entry.request.price, 104)

        strategy.on_tick(Tick(
            CONTRACT, 98, open_price=100, ask_price=99, bid_price=97,
        ))
        self.assertEqual(strategy.position_side, "flat")
        orders = list(engine.orders.values())
        self.assertEqual(len(orders), 2)
        self.assertEqual(orders[1].request.offset, Offset.CLOSE_TODAY)
        self.assertEqual(orders[1].request.price, 97)
        engine.close()

    def test_observe_mode_records_signal_without_order(self):
        engine = self.engine()
        strategy = FuturesTrendStrategy(CONTRACT, execute=False)
        strategy.bind(engine)
        strategy.trend_filter = _LongTrend()
        strategy.setup = EntrySetup("long", 102, 99, 10)

        strategy.on_tick(Tick(CONTRACT, 103, open_price=100, ask_price=104))

        self.assertIsNotNone(strategy.last_signal)
        self.assertEqual(engine.orders, {})
        self.assertEqual(strategy.position_side, "flat")
        engine.close()

    def test_short_entry_and_stop_buy_close_short_today(self):
        engine = self.engine()
        strategy = FuturesTrendStrategy(CONTRACT, execute=True)
        strategy.bind(engine)
        strategy.trend_filter = _ShortTrend()
        strategy.setup = EntrySetup("short", 98, 101, 10)

        strategy.on_tick(Tick(
            CONTRACT, 97, open_price=100, ask_price=98, bid_price=96,
        ))
        self.assertEqual(strategy.position_side, "short")
        entry = next(iter(engine.orders.values()))
        self.assertEqual(entry.request.offset, Offset.OPEN)
        self.assertEqual(entry.request.side.value, "S")
        self.assertEqual(entry.request.price, 96)

        strategy.on_tick(Tick(
            CONTRACT, 102, open_price=100, ask_price=103, bid_price=101,
        ))
        self.assertEqual(strategy.position_side, "flat")
        exit_order = list(engine.orders.values())[1]
        self.assertEqual(exit_order.request.offset, Offset.CLOSE_TODAY)
        self.assertEqual(exit_order.request.side.value, "B")
        self.assertEqual(exit_order.request.price, 103)
        engine.close()

    def test_partial_entry_remains_visible_after_cancel(self):
        bus = EventBus()
        engine = TradingEngine(
            lambda sink: MockGateway(sink, auto_fill=False), event_bus=bus,
        )
        engine.connect()
        strategy = FuturesTrendStrategy(CONTRACT, volume=2, execute=True)
        strategy.bind(engine)
        strategy.setup = EntrySetup("long", 102, 99, 10)
        strategy._submit_entry("long", 103)
        client_id = strategy.entry_order
        order = engine.orders[client_id]

        bus.publish(Event("order", {
            "request_id": order.request_id,
            "order_id": order.order_id,
            "status": "partially_filled",
            "traded_volume": 1,
        }))
        strategy._sync_order_state()
        self.assertEqual((strategy.position_side, strategy.position_volume), ("long", 1))

        bus.publish(Event("order", {
            "request_id": order.request_id,
            "order_id": order.order_id,
            "status": "cancelled",
            "traded_volume": 1,
        }))
        strategy._sync_order_state()
        self.assertIsNone(strategy.entry_order)
        self.assertEqual((strategy.position_side, strategy.position_volume), ("long", 1))
        engine.close()


if __name__ == "__main__":
    unittest.main()
