import unittest
import tempfile
import sqlite3
from contextlib import closing
from pathlib import Path

from quant_framework.cli import _builtin_intervals, _load_strategies, _parser, main
from quant_framework.strategy import FuturesTrendStrategy


class CliTests(unittest.TestCase):
    def test_builtin_strategy_expands_to_every_contract(self):
        contracts = ["DCE|F|P|2701", "DCE|F|M|2701", "DCE|F|Y|2701"]
        loaded = _load_strategies("five-minute-pivot", contracts, False)
        self.assertEqual(len(loaded), 3)
        self.assertEqual(
            [strategy.contract for _name, strategy in loaded],
            contracts,
        )

    def test_pivot_strategy_accepts_any_positive_interval(self):
        loaded = _load_strategies(
            "pivot:60", ["DCE|F|P|2701"], False,
        )
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0][1].interval_seconds, 60)

    def test_futures_trend_strategy_adds_three_minute_and_hourly_bars(self):
        loaded = _load_strategies(
            "futures-trend", ["DCE|F|P|2701"], False, 2,
        )
        self.assertIsInstance(loaded[0][1], FuturesTrendStrategy)
        self.assertEqual(loaded[0][1].volume, 2)
        self.assertEqual(_builtin_intervals("futures-trend"), (180, 3600))

    def test_ctp_gateway_is_available(self):
        args = _parser().parse_args([
            "--gateway", "ctp", "--config", "config/ctp.toml",
            "funds",
        ])
        self.assertEqual(args.gateway, "ctp")
        self.assertEqual(args.action, "funds")

    def test_unified_mock_runtime_starts_and_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "ticks.sqlite3")
            result = main([
                "--gateway", "mock", "run",
                "--contract", "DCE|F|P|2701",
                "--strategy", "five-minute-pivot",
                "--trading-day", "2026-09-16",
                "--database", database,
                "--run-seconds", "0.01",
            ])
            self.assertEqual(result, 0)
            self.assertTrue(Path(database).is_file())

    def test_unified_runtime_runs_builtin_strategy_for_multiple_contracts(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "ticks.sqlite3")
            result = main([
                "--gateway", "mock", "run",
                "--contract", "DCE|F|P|2701",
                "--contract", "DCE|F|M|2701",
                "--strategy", "five-minute-pivot",
                "--trading-day", "2026-09-16",
                "--database", database,
                "--run-seconds", "0.01",
            ])
            self.assertEqual(result, 0)

    def test_one_off_order_is_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "market.sqlite3")
            result = main([
                "--gateway", "mock", "buy",
                "--contract", "DCE|F|P|2701",
                "--price", "10100", "--volume", "1",
                "--database", database,
                "--trading-day", "2026-09-16",
            ])
            self.assertEqual(result, 0)
            with closing(sqlite3.connect(database)) as connection:
                order = connection.execute(
                    "SELECT status, requested_volume FROM orders",
                ).fetchone()
                trade = connection.execute(
                    "SELECT price, volume FROM trades",
                ).fetchone()
            self.assertEqual(order, ("filled", 1))
            self.assertEqual(trade, (10100.0, 1))


if __name__ == "__main__":
    unittest.main()
