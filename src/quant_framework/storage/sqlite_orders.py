from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from ..core.models import Order


class SQLiteOrderStore:
    """Persist current orders, their state history, and actual fills."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS orders (
                client_order_id TEXT PRIMARY KEY,
                gateway TEXT NOT NULL,
                account TEXT NOT NULL,
                trading_day TEXT NOT NULL,
                request_id INTEGER NOT NULL,
                reference INTEGER,
                order_id INTEGER NOT NULL DEFAULT 0,
                system_no TEXT NOT NULL DEFAULT '',
                contract TEXT NOT NULL,
                side TEXT NOT NULL,
                offset TEXT NOT NULL,
                hedge TEXT NOT NULL,
                order_type TEXT NOT NULL,
                time_in_force TEXT NOT NULL,
                limit_price REAL NOT NULL,
                requested_volume INTEGER NOT NULL,
                min_volume INTEGER NOT NULL,
                traded_volume INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                error_code INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '',
                submitted_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_orders_contract_day_time
                ON orders(contract, trading_day, submitted_at);

            CREATE TABLE IF NOT EXISTS order_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_order_id TEXT NOT NULL,
                gateway TEXT NOT NULL,
                account TEXT NOT NULL,
                trading_day TEXT NOT NULL,
                order_id INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                traded_volume INTEGER NOT NULL DEFAULT 0,
                error_code INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '',
                event_time TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_order_events_client_time
                ON order_events(client_order_id, event_time);

            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gateway TEXT NOT NULL,
                account TEXT NOT NULL,
                trading_day TEXT NOT NULL,
                client_order_id TEXT NOT NULL DEFAULT '',
                trade_id TEXT NOT NULL DEFAULT '',
                order_id INTEGER NOT NULL DEFAULT 0,
                contract TEXT NOT NULL,
                trade_time TEXT NOT NULL,
                received_at TEXT NOT NULL,
                side TEXT NOT NULL,
                offset TEXT NOT NULL,
                price REAL NOT NULL,
                volume INTEGER NOT NULL,
                fee REAL NOT NULL DEFAULT 0,
                label TEXT NOT NULL DEFAULT '',
                UNIQUE(gateway, account, trading_day, trade_id, order_id, price, volume)
            );
            CREATE INDEX IF NOT EXISTS ix_trades_contract_day_time
                ON trades(contract, trading_day, trade_time);
        """)
        self._connection.commit()

    def save_order(
        self,
        order: Order,
        *,
        gateway: str,
        account: str,
        trading_day: str,
        event_time: datetime,
    ) -> None:
        request = order.request
        timestamp = event_time.isoformat()
        reference = request.reference if request.reference is not None else order.request_id
        values = (
            order.client_order_id, gateway, account, trading_day,
            order.request_id, reference, order.order_id, order.system_no,
            request.contract, request.side.value, request.offset.value,
            request.hedge.value, request.order_type.value, request.time_in_force.value,
            request.price, request.volume, request.min_volume, order.traded_volume,
            order.status.value, order.error_code, order.message, timestamp, timestamp,
        )
        with self._lock:
            self._connection.execute("""
                INSERT INTO orders (
                    client_order_id, gateway, account, trading_day,
                    request_id, reference, order_id, system_no,
                    contract, side, offset, hedge, order_type, time_in_force,
                    limit_price, requested_volume, min_volume, traded_volume,
                    status, error_code, message, submitted_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(client_order_id) DO UPDATE SET
                    order_id=excluded.order_id,
                    system_no=excluded.system_no,
                    traded_volume=excluded.traded_volume,
                    status=excluded.status,
                    error_code=excluded.error_code,
                    message=excluded.message,
                    updated_at=excluded.updated_at
            """, values)
            self._connection.execute("""
                INSERT INTO order_events (
                    client_order_id, gateway, account, trading_day, order_id,
                    status, traded_volume, error_code, message, event_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                order.client_order_id, gateway, account, trading_day, order.order_id,
                order.status.value, order.traded_volume, order.error_code,
                order.message, timestamp,
            ))
            self._connection.commit()

    def save_trade(
        self,
        trade: dict,
        *,
        gateway: str,
        account: str,
        trading_day: str,
    ) -> int:
        with self._lock:
            before = self._connection.total_changes
            self._connection.execute("""
                INSERT OR IGNORE INTO trades (
                    gateway, account, trading_day, client_order_id,
                    trade_id, order_id, contract, trade_time, received_at,
                    side, offset, price, volume, fee, label
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                gateway, account, trading_day,
                str(trade.get("client_order_id", "")),
                str(trade.get("trade_id", "")), int(trade.get("order_id", 0)),
                str(trade.get("contract", "")), str(trade.get("trade_time", "")),
                str(trade.get("received_at", "")), str(trade.get("side", "")),
                str(trade.get("offset", "")), float(trade.get("price", 0)),
                int(trade.get("volume", 0)), float(trade.get("fee", 0)),
                str(trade.get("label", "")),
            ))
            self._connection.commit()
            return self._connection.total_changes - before

    def close(self) -> None:
        with self._lock:
            if self._connection is None:
                return
            self._connection.close()
            self._connection = None
