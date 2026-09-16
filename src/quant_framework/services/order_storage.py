from __future__ import annotations

import logging
import queue
import threading

from ..core.events import EventBus
from ..core.models import Event, Order
from ..storage import SQLiteOrderStore


class OrderStorageService:
    """Persist normalized order and trade events without blocking strategies."""

    def __init__(
        self,
        event_bus: EventBus,
        store: SQLiteOrderStore,
        *,
        gateway: str,
        account: str,
        trading_day: str,
        queue_size: int = 10_000,
    ) -> None:
        if queue_size <= 0:
            raise ValueError("queue_size 必须大于 0")
        self.store = store
        self.gateway = gateway
        self.account = account
        self.trading_day = trading_day
        self._queue: queue.Queue[Event | None] = queue.Queue(maxsize=queue_size)
        self._thread: threading.Thread | None = None
        self._log = logging.getLogger(__name__)
        self.persisted_orders = 0
        self.persisted_trades = 0
        self.dropped_events = 0
        self.failed_events = 0
        event_bus.subscribe("order.snapshot", self._enqueue)
        event_bus.subscribe("trade.normalized", self._enqueue)

    @property
    def queued_events(self) -> int:
        return self._queue.qsize()

    @property
    def queue_capacity(self) -> int:
        return self._queue.maxsize

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, name="order-storage", daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        if self._thread:
            self._queue.put(None)
            self._thread.join(timeout=30)
            if self._thread.is_alive():
                raise TimeoutError("订单存储队列未能在30秒内排空")
            self._thread = None
        self.store.close()

    def _enqueue(self, event: Event) -> None:
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            self.dropped_events += 1

    def _run(self) -> None:
        while True:
            event = self._queue.get()
            if event is None:
                return
            try:
                if event.type == "order.snapshot":
                    if not isinstance(event.data, Order):
                        raise TypeError("order.snapshot 事件数据必须是 Order")
                    self.store.save_order(
                        event.data, gateway=self.gateway, account=self.account,
                        trading_day=self.trading_day, event_time=event.created_at,
                    )
                    self.persisted_orders += 1
                elif event.type == "trade.normalized":
                    if not isinstance(event.data, dict):
                        raise TypeError("trade.normalized 事件数据必须是 dict")
                    self.persisted_trades += self.store.save_trade(
                        event.data, gateway=self.gateway, account=self.account,
                        trading_day=self.trading_day,
                    )
            except Exception:
                self.failed_events += 1
                self._log.exception("订单/成交数据写入失败: %s", event.type)
