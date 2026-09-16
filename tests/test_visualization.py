import sqlite3
import tempfile
import unittest
from pathlib import Path
from urllib.request import urlopen

from quant_framework.core import Event, EventBus, Tick
from quant_framework.services.chart_feed import LiveChartFeed
from quant_framework.storage import SQLiteTickStore
from quant_framework.visualization import (
    ChartBar,
    DatabaseChartProvider,
    LiveChartServer,
    SQLiteChartRepository,
    detect_bottom_pivots,
    detect_pivots,
    write_chart_report,
)


class VisualizationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "ticks.sqlite3"
        with SQLiteTickStore(self.database, "2026-09-16") as store:
            for timestamp, price, last_volume, total_volume in (
                ("2026-09-16 09:00:01", 100.0, 2, 2),
                ("2026-09-16 09:01:01", 103.0, 3, 5),
                ("2026-09-16 09:04:01", 99.0, 1, 6),
                ("2026-09-16 09:05:01", 101.0, 4, 10),
            ):
                store.append(Tick(
                    contract="DCE|F|P|2701", timestamp=timestamp,
                    last_price=price, last_volume=last_volume,
                    total_volume=total_volume, open_interest=1000,
                ))
        connection = sqlite3.connect(self.database)
        connection.execute("""
            CREATE TABLE trades (
                contract TEXT, trading_day TEXT, trade_time TEXT,
                side TEXT, offset TEXT, price REAL, volume INTEGER, label TEXT
            )
        """)
        connection.execute(
            "INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("DCE|F|P|2701", "2026-09-16", "2026-09-16 09:01:30",
             "buy", "open", 102.0, 1, "买开"),
        )
        connection.commit()
        connection.close()

    def tearDown(self):
        self.temporary.cleanup()

    def test_repository_aggregates_bars_and_loads_trades(self):
        data = SQLiteChartRepository(self.database).load(
            "DCE|F|P|2701", 300, "2026-09-16",
        )
        self.assertEqual(len(data.bars), 2)
        self.assertEqual(
            (data.bars[0].open, data.bars[0].high, data.bars[0].low, data.bars[0].close),
            (100.0, 103.0, 99.0, 99.0),
        )
        self.assertEqual(data.bars[0].volume, 6)
        self.assertEqual(data.trades[0].label, "买开")

    def test_chart_marks_the_same_confirmed_bottom_pivot_as_strategy(self):
        bars = (
            ChartBar("2026-09-16T09:00:00", 99, 101, 98, 99, 1, 1000),
            ChartBar("2026-09-16T09:05:00", 96, 100, 95, 96, 1, 1000),
            ChartBar("2026-09-16T09:10:00", 97, 103, 97, 102, 1, 1000),
        )
        pivots = detect_bottom_pivots("DCE|F|P|2701", bars, 300)
        self.assertEqual(len(pivots), 1)
        self.assertEqual(pivots[0].time, "2026-09-16T09:05:00")
        self.assertEqual(pivots[0].price, 95)

        unfinished = bars[:-1] + (
            ChartBar(
                "2026-09-16T09:10:00", 97, 103, 97, 102, 1, 1000,
                complete=False,
            ),
        )
        self.assertEqual(
            detect_bottom_pivots("DCE|F|P|2701", unfinished, 300), (),
        )

        one_minute = (
            ChartBar("2026-09-16T09:00:00", 99, 101, 98, 99, 1, 1000),
            ChartBar("2026-09-16T09:01:00", 96, 100, 95, 96, 1, 1000),
            ChartBar("2026-09-16T09:02:00", 97, 103, 97, 102, 1, 1000),
        )
        self.assertEqual(
            len(detect_bottom_pivots("DCE|F|P|2701", one_minute, 60)), 1,
        )

        top_bars = (
            ChartBar("2026-09-16T10:00:00", 100, 101, 98, 100, 1, 1000),
            ChartBar("2026-09-16T10:01:00", 104, 105, 99, 104, 1, 1000),
            ChartBar("2026-09-16T10:02:00", 102, 103, 96, 98, 1, 1000),
        )
        top = detect_pivots("DCE|F|P|2701", top_bars, 60)
        self.assertEqual(len(top), 1)
        self.assertEqual((top[0].kind, top[0].price, top[0].label),
                         ("top", 105, "顶部拐点"))

    def test_report_and_live_server(self):
        provider = DatabaseChartProvider(
            str(self.database), "DCE|F|P|2701", 300, "2026-09-16",
        )
        output = write_chart_report(provider.snapshot(), Path(self.temporary.name) / "report.html")
        html = output.read_text(encoding="utf-8")
        self.assertIn("DCE|F|P|2701", html)
        self.assertIn("买开", html)

        server = LiveChartServer(provider, port=0)
        try:
            server.start()
            duplicate = LiveChartServer(provider, port=server.port)
            with self.assertRaises(OSError):
                duplicate.start()
            with urlopen(server.url + "api/chart", timeout=3) as response:
                payload = response.read().decode("utf-8")
            self.assertIn('"bars"', payload)
            self.assertIn('"pivots"', payload)
            self.assertIn("DCE|F|P|2701", payload)
        finally:
            server.close()

    def test_live_feed_uses_bounded_non_blocking_queue(self):
        events = EventBus()
        feed = LiveChartFeed(
            events, "DCE|F|P|2701", "2026-09-16", 300, queue_size=1,
        )
        events.publish(Event("tick", Tick(
            contract="DCE|F|P|2701", timestamp="2026-09-16 09:00:01",
            last_price=100, last_volume=1, total_volume=1,
        )))
        events.publish(Event("tick", Tick(
            contract="DCE|F|P|2701", timestamp="2026-09-16 09:00:02",
            last_price=101, last_volume=1, total_volume=2,
        )))
        self.assertEqual(feed.dropped_events, 1)
        feed.start()
        feed.close()
        snapshot = feed.snapshot()
        self.assertEqual(len(snapshot.bars), 1)
        self.assertEqual(snapshot.bars[0].close, 100)


if __name__ == "__main__":
    unittest.main()
