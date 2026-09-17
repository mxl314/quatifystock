from __future__ import annotations

import sqlite3
from pathlib import Path

from ..core.models import Tick
from .aggregation import aggregate_ticks
from .models import ChartData, TradeMarker
from .pivots import detect_pivots


class SQLiteChartRepository:
    """Read-only chart queries for the market database."""

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)

    def load(
        self,
        contract: str,
        interval_seconds: int,
        trading_day: str | None = None,
    ) -> ChartData:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds 必须大于 0")
        if not self.database.is_file():
            raise FileNotFoundError(f"数据库不存在: {self.database}")
        connection = sqlite3.connect(
            f"file:{self.database.resolve().as_posix()}?mode=ro", uri=True,
        )
        connection.row_factory = sqlite3.Row
        try:
            day = trading_day or self._latest_day(connection, contract)
            ticks = self._ticks(connection, contract, day)
            trades = self._trades(connection, contract, day)
        finally:
            connection.close()
        bars = aggregate_ticks(ticks, interval_seconds)
        return ChartData(
            contract=contract,
            trading_day=day,
            interval_seconds=interval_seconds,
            bars=bars,
            trades=trades,
            pivots=detect_pivots(contract, bars, interval_seconds),
        )

    @staticmethod
    def _latest_day(connection: sqlite3.Connection, contract: str) -> str:
        row = connection.execute(
            "SELECT MAX(trading_day) FROM ticks WHERE contract = ?", (contract,),
        ).fetchone()
        if not row or not row[0]:
            raise LookupError(f"没有找到合约 {contract} 的 Tick 数据")
        return str(row[0])

    @staticmethod
    def _ticks(
        connection: sqlite3.Connection, contract: str, trading_day: str,
    ) -> tuple[Tick, ...]:
        rows = connection.execute(
            """
            SELECT contract, exchange_timestamp, last_price, last_volume,
                   bid_price, bid_volume, ask_price, ask_volume,
                   open_price, high_price, low_price, pre_settlement,
                   upper_limit, lower_limit, total_volume, open_interest
              FROM ticks
             WHERE contract = ? AND trading_day = ?
             ORDER BY id
            """,
            (contract, trading_day),
        ).fetchall()
        if not rows:
            raise LookupError(f"没有找到 {contract} 在 {trading_day} 的 Tick 数据")
        return tuple(
            Tick(
                contract=row["contract"], timestamp=row["exchange_timestamp"],
                last_price=row["last_price"], last_volume=row["last_volume"],
                bid_price=row["bid_price"], bid_volume=row["bid_volume"],
                ask_price=row["ask_price"], ask_volume=row["ask_volume"],
                open_price=row["open_price"], high_price=row["high_price"],
                low_price=row["low_price"], pre_settlement=row["pre_settlement"],
                upper_limit=row["upper_limit"], lower_limit=row["lower_limit"],
                total_volume=row["total_volume"], open_interest=row["open_interest"],
            )
            for row in rows
        )

    @staticmethod
    def _trades(
        connection: sqlite3.Connection, contract: str, trading_day: str,
    ) -> tuple[TradeMarker, ...]:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='trades'",
        ).fetchone()
        if not exists:
            return ()
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(trades)")
        }
        required = {"contract", "trading_day", "trade_time", "side", "price"}
        if not required.issubset(columns):
            return ()
        offset = "offset" if "offset" in columns else "''"
        volume = "volume" if "volume" in columns else "0"
        label = "label" if "label" in columns else "''"
        rows = connection.execute(
            f"""
            SELECT trade_time, price, side, {offset} AS offset,
                   {volume} AS volume, {label} AS label
              FROM trades
             WHERE contract = ? AND trading_day = ?
             ORDER BY trade_time
            """,  # nosec B608: identifiers are selected from a fixed allowlist above
            (contract, trading_day),
        ).fetchall()
        return tuple(
            TradeMarker(
                time=str(row["trade_time"]).replace(" ", "T", 1),
                price=float(row["price"]),
                side=str(row["side"]), offset=str(row["offset"] or ""),
                volume=int(row["volume"] or 0), label=str(row["label"] or ""),
            )
            for row in rows
        )
