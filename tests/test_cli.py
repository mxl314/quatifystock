import unittest
import tempfile
from pathlib import Path

from quant_framework.cli import _parser, main


class CliTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
