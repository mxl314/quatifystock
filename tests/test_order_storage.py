import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_framework.adapters.mock import MockGateway, MockQuoteGateway
from quant_framework.core import Offset, OrderRequest, OrderStatus, Side
from quant_framework.core.models import Order
from quant_framework.runtime import LiveRuntime
from quant_framework.storage import SQLiteOrderStore, SQLiteTickStore


class OrderStorageTests(unittest.TestCase):
    def test_identical_consecutive_order_snapshots_are_deduplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.sqlite3"
            store = SQLiteOrderStore(path)
            started = datetime(2026, 9, 17, tzinfo=timezone.utc)
            order = Order(
                "client-1", 1,
                OrderRequest("DCE|F|P|2701", Side.BUY, Offset.OPEN, 2, 10100),
            )
            self.assertEqual(store.save_order(
                order, gateway="mock", account="simulation",
                trading_day="2026-09-17", event_time=started,
            ), 1)

            order.order_id = 123
            order.status = OrderStatus.ACCEPTED
            self.assertEqual(store.save_order(
                order, gateway="mock", account="simulation",
                trading_day="2026-09-17", event_time=started + timedelta(seconds=1),
            ), 1)
            self.assertEqual(store.save_order(
                order, gateway="mock", account="simulation",
                trading_day="2026-09-17", event_time=started + timedelta(seconds=2),
            ), 0)

            order.status = OrderStatus.PARTIALLY_FILLED
            order.traded_volume = 1
            self.assertEqual(store.save_order(
                order, gateway="mock", account="simulation",
                trading_day="2026-09-17", event_time=started + timedelta(seconds=3),
            ), 1)
            order.traded_volume = 2
            self.assertEqual(store.save_order(
                order, gateway="mock", account="simulation",
                trading_day="2026-09-17", event_time=started + timedelta(seconds=4),
            ), 1)
            store.close()

            with closing(sqlite3.connect(path)) as connection:
                events = connection.execute("""
                    SELECT status, traded_volume FROM order_events
                     WHERE client_order_id = ? ORDER BY id
                """, (order.client_order_id,)).fetchall()
            self.assertEqual(events, [
                ("submitting", 0),
                ("accepted", 0),
                ("partially_filled", 1),
                ("partially_filled", 2),
            ])

    def test_runtime_persists_order_history_and_trade(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.sqlite3"
            runtime = LiveRuntime(
                market_factory=lambda sink: MockQuoteGateway(sink),
                trading_factory=lambda sink: MockGateway(sink, auto_fill=True),
                tick_store=SQLiteTickStore(path, "2026-09-16", batch_size=500),
                order_store=SQLiteOrderStore(path),
                gateway_name="mock",
                account="simulation",
                trading_day="2026-09-16",
            )
            runtime.connect()
            runtime.subscribe("DCE|F|P|2701")
            runtime.market.gateway.push_tick("DCE|F|P|2701", 10100)
            client_id = runtime.trading.buy("DCE|F|P|2701", 10100, 2)
            runtime.close()

            with closing(sqlite3.connect(path)) as connection:
                order = connection.execute("""
                    SELECT client_order_id, contract, side, offset, limit_price,
                           requested_volume, traded_volume, status
                      FROM orders
                """).fetchone()
                events = connection.execute("""
                    SELECT status FROM order_events
                     WHERE client_order_id = ? ORDER BY id
                """, (client_id,)).fetchall()
                trade = connection.execute("""
                    SELECT contract, side, offset, price, volume, label
                      FROM trades
                """).fetchone()
                tick_count = connection.execute(
                    "SELECT COUNT(*) FROM ticks",
                ).fetchone()[0]

            self.assertEqual(order, (
                client_id, "DCE|F|P|2701", "B", "O", 10100.0,
                2, 2, "filled",
            ))
            self.assertEqual(
                events,
                [("submitting",), ("accepted",), ("filled",)],
            )
            self.assertEqual(
                trade,
                ("DCE|F|P|2701", "B", "O", 10100.0, 2, "买开"),
            )
            self.assertEqual(tick_count, 1)


if __name__ == "__main__":
    unittest.main()
