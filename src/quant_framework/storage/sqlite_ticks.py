from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..core.models import Tick


class SQLiteTickStore:
    """Batch and deduplicate canonical ticks in a local SQLite database."""

    _INSERT = """
        INSERT OR IGNORE INTO ticks (
            trading_day, contract, exchange_timestamp, received_at,
            last_price, last_volume, bid_price, bid_volume, ask_price, ask_volume,
            open_price, high_price, low_price, pre_settlement,
            upper_limit, lower_limit, total_volume, open_interest
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    def __init__(self, path: str | Path, trading_day: str, *, batch_size: int = 500) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size 必须大于 0")
        datetime.strptime(trading_day, "%Y-%m-%d")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.trading_day = trading_day
        self.batch_size = batch_size
        self._lock = threading.RLock()
        self._pending: list[tuple] = []
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS ticks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trading_day TEXT NOT NULL,
                contract TEXT NOT NULL,
                exchange_timestamp TEXT NOT NULL,
                received_at TEXT NOT NULL,
                last_price REAL NOT NULL,
                last_volume INTEGER NOT NULL,
                bid_price REAL NOT NULL,
                bid_volume INTEGER NOT NULL,
                ask_price REAL NOT NULL,
                ask_volume INTEGER NOT NULL,
                open_price REAL NOT NULL,
                high_price REAL NOT NULL,
                low_price REAL NOT NULL,
                pre_settlement REAL NOT NULL,
                upper_limit REAL NOT NULL,
                lower_limit REAL NOT NULL,
                total_volume INTEGER NOT NULL,
                open_interest INTEGER NOT NULL,
                UNIQUE(contract, exchange_timestamp, total_volume, last_price,
                       bid_price, bid_volume, ask_price, ask_volume)
            );
            CREATE INDEX IF NOT EXISTS ix_ticks_contract_day_time
                ON ticks(contract, trading_day, exchange_timestamp);
        """)
        self._connection.commit()

    def append(self, tick: Tick, *, received_at: datetime | None = None) -> None:
        received_at = received_at or datetime.now(timezone.utc)
        timestamp = tick.timestamp.isoformat() if isinstance(tick.timestamp, datetime) else str(tick.timestamp)
        row = (
            self.trading_day, tick.contract, timestamp, received_at.astimezone(timezone.utc).isoformat(),
            tick.last_price, tick.last_volume, tick.bid_price, tick.bid_volume,
            tick.ask_price, tick.ask_volume, tick.open_price, tick.high_price,
            tick.low_price, tick.pre_settlement, tick.upper_limit, tick.lower_limit,
            tick.total_volume, tick.open_interest,
        )
        with self._lock:
            self._pending.append(row)
            if len(self._pending) >= self.batch_size:
                self._flush_unlocked()

    def flush(self) -> int:
        with self._lock:
            return self._flush_unlocked()

    def _flush_unlocked(self) -> int:
        if not self._pending:
            return 0
        before = self._connection.total_changes
        self._connection.executemany(self._INSERT, self._pending)
        self._connection.commit()
        self._pending.clear()
        return self._connection.total_changes - before

    def count(self, contract: str | None = None, trading_day: str | None = None) -> int:
        self.flush()
        sql = "SELECT COUNT(*) FROM ticks"
        clauses: list[str] = []
        values: list[str] = []
        if contract:
            clauses.append("contract = ?")
            values.append(contract)
        if trading_day:
            clauses.append("trading_day = ?")
            values.append(trading_day)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        with self._lock:
            return int(self._connection.execute(sql, values).fetchone()[0])

    def close(self) -> None:
        with self._lock:
            if self._connection is None:
                return
            self._flush_unlocked()
            self._connection.close()
            self._connection = None

    def __enter__(self) -> "SQLiteTickStore":
        return self

    def __exit__(self, *_args) -> None:
        self.close()
