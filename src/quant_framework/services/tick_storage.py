from __future__ import annotations

import logging
import queue
import threading
import time

from ..core.events import EventBus
from ..core.models import Event, Tick
from ..storage import SQLiteTickStore


class TickStorageService:
    """Persist ticks on a worker fed by non-blocking event callbacks."""

    def __init__(
        self,
        event_bus: EventBus,
        store: SQLiteTickStore,
        *,
        flush_seconds: float = 60,
        queue_size: int = 50_000,
    ) -> None:
        if flush_seconds <= 0:
            raise ValueError("flush_seconds 必须大于 0")
        if queue_size <= 0:
            raise ValueError("queue_size 必须大于 0")
        self.store = store
        self.flush_seconds = flush_seconds
        self._queue: queue.Queue[Event | None] = queue.Queue(maxsize=queue_size)
        self._thread: threading.Thread | None = None
        self._log = logging.getLogger(__name__)
        self.enqueued_events = 0
        self.processed_events = 0
        self.persisted_rows = 0
        self.dropped_events = 0
        self.failed_events = 0
        self.failed_flushes = 0
        event_bus.subscribe("tick", self._enqueue)

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
            target=self._run, name="tick-storage", daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        if self._thread:
            self._queue.put(None)
            self._thread.join(timeout=30)
            if self._thread.is_alive():
                raise TimeoutError("Tick 存储队列未能在30秒内排空")
            self._thread = None
        self.store.close()

    def _enqueue(self, event: Event) -> None:
        tick = event.data
        if not isinstance(tick, Tick):
            raise TypeError("tick 事件数据必须是 Tick")
        try:
            self._queue.put_nowait(event)
            self.enqueued_events += 1
        except queue.Full:
            self.dropped_events += 1

    def _run(self) -> None:
        next_flush = time.monotonic() + self.flush_seconds
        while True:
            timeout = max(0, next_flush - time.monotonic())
            try:
                event = self._queue.get(timeout=timeout)
            except queue.Empty:
                self._flush()
                next_flush = time.monotonic() + self.flush_seconds
                continue
            if event is None:
                break
            tick = event.data
            try:
                self.persisted_rows += self.store.append(
                    tick, received_at=event.created_at,
                )
                self.processed_events += 1
            except Exception:
                self.failed_events += 1
                self._log.exception("写入 Tick 数据失败")
            if time.monotonic() >= next_flush:
                self._flush()
                next_flush = time.monotonic() + self.flush_seconds
        self._flush()

    def _flush(self) -> None:
        try:
            self.persisted_rows += self.store.flush()
        except Exception:
            self.failed_flushes += 1
            self._log.exception("提交 Tick 数据失败")
