from __future__ import annotations

import logging
import threading

from ..core.events import EventBus
from ..core.models import Event, Tick
from ..storage import SQLiteTickStore


class TickStorageService:
    """Persist tick events without coupling storage calls to a strategy."""

    def __init__(
        self,
        event_bus: EventBus,
        store: SQLiteTickStore,
        *,
        flush_seconds: float = 60,
    ) -> None:
        if flush_seconds <= 0:
            raise ValueError("flush_seconds 必须大于 0")
        self.store = store
        self.flush_seconds = flush_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._log = logging.getLogger(__name__)
        event_bus.subscribe("tick", self._on_tick)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._flush_loop, name="tick-storage", daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=min(self.flush_seconds + 1, 5))
            self._thread = None
        self.store.close()

    def _on_tick(self, event: Event) -> None:
        tick = event.data
        if not isinstance(tick, Tick):
            raise TypeError("tick 事件数据必须是 Tick")
        self.store.append(tick, received_at=event.created_at)

    def _flush_loop(self) -> None:
        while not self._stop.wait(self.flush_seconds):
            try:
                self.store.flush()
            except Exception:
                self._log.exception("定时写入 Tick 数据失败")
