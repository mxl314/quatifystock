import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from quant_framework.core.models import Tick
from quant_framework.adapters.mock import MockGateway, MockQuoteGateway
from quant_framework.runtime import LiveRuntime
from quant_framework.storage import SQLiteTickStore


class SQLiteTickStoreTests(unittest.TestCase):
    def test_one_contract_is_kept_together_across_trading_days(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market_ticks.sqlite3"
            tick1 = Tick("DCE|F|P|2701", 10030, "2026-09-15 21:00:00.100",
                         total_volume=10, bid_price=10029, ask_price=10030)
            tick2 = Tick("DCE|F|P|2701", 10031, "2026-09-16 09:00:00.100",
                         total_volume=11, bid_price=10030, ask_price=10031)
            with SQLiteTickStore(path, "2026-09-16", batch_size=10) as store:
                store.append(tick1)
            with SQLiteTickStore(path, "2026-09-17", batch_size=10) as store:
                store.append(tick2)
                self.assertEqual(store.count("DCE|F|P|2701"), 2)
                self.assertEqual(store.count("DCE|F|P|2701", "2026-09-16"), 1)
                self.assertEqual(store.count("DCE|F|P|2701", "2026-09-17"), 1)
            with closing(sqlite3.connect(path)) as connection:
                days = connection.execute(
                    "SELECT trading_day FROM ticks ORDER BY exchange_timestamp"
                ).fetchall()
            self.assertEqual(days, [("2026-09-16",), ("2026-09-17",)])

    def test_duplicate_tick_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market_ticks.sqlite3"
            tick = Tick("DCE|F|P|2701", 10030, "2026-09-16 09:00:00.100",
                        total_volume=10, bid_price=10029, ask_price=10030)
            with SQLiteTickStore(path, "2026-09-16", batch_size=1) as store:
                store.append(tick)
                store.append(tick)
                self.assertEqual(store.count(), 1)

    def test_live_runtime_persists_the_same_ticks_delivered_to_strategy_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market_ticks.sqlite3"
            store = SQLiteTickStore(path, "2026-09-16", batch_size=500)
            runtime = LiveRuntime(
                market_factory=lambda sink: MockQuoteGateway(sink),
                trading_factory=lambda sink: MockGateway(sink),
                tick_store=store,
                tick_flush_seconds=60,
            )
            runtime.connect()
            runtime.subscribe("DCE|F|P|2701")
            runtime.market.gateway.push_tick("DCE|F|P|2701", 10030)
            runtime.close()
            with closing(sqlite3.connect(path)) as connection:
                row = connection.execute(
                    "SELECT contract, last_price FROM ticks"
                ).fetchone()
            self.assertEqual(row, ("DCE|F|P|2701", 10030.0))


if __name__ == "__main__":
    unittest.main()
