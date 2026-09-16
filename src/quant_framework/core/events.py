from __future__ import annotations

import logging
import queue
import threading
from collections import defaultdict
from collections.abc import Callable

from .models import Event

EventHandler = Callable[[Event], None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._queue: queue.Queue[Event | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._log = logging.getLogger(__name__)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)

    def publish(self, event: Event) -> None:
        self._queue.put(event) if self._running.is_set() else self._dispatch(event)

    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._run, name="event-bus", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._running.is_set():
            return
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        self._running.clear()

    def _run(self) -> None:
        while True:
            event = self._queue.get()
            if event is None:
                break
            self._dispatch(event)

    def _dispatch(self, event: Event) -> None:
        for handler in tuple(self._handlers.get(event.type, ())):
            try:
                handler(event)
            except Exception:
                self._log.exception("事件处理失败: %s", event.type)
