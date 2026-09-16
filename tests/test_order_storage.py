import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from quant_framework.adapters.mock import MockGateway, MockQuoteGateway
from quant_framework.runtime import LiveRuntime
from quant_framework.storage import SQLiteOrderStore, SQLiteTickStore


class OrderStorageTests(unittest.TestCase):
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
