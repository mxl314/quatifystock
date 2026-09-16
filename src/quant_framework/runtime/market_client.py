from __future__ import annotations

import threading

from ..core.events import EventBus
from ..core.interfaces import MarketDataGateway


class QuoteClient:
    def __init__(self, gateway_factory, *, event_bus: EventBus | None = None) -> None:
        self.events = event_bus or EventBus()
        self.gateway: MarketDataGateway = gateway_factory(self.events.publish)
        self.ready = threading.Event()
        self.error: object | None = None
        self.events.subscribe("quote.ready", lambda _event: self.ready.set())
        self.events.subscribe("quote.error", self._on_error)

    def connect(self, timeout: float = 30) -> None:
        self.gateway.connect()
        if not self.ready.wait(timeout):
            raise TimeoutError("等待行情 API Ready 超时")
        if self.error is not None:
            raise RuntimeError(f"行情网关连接失败: {self.error}")

    def subscribe(self, *contracts: str) -> None:
        for contract in contracts:
            self.gateway.subscribe(contract)

    def unsubscribe(self, *contracts: str) -> None:
        for contract in contracts:
            self.gateway.unsubscribe(contract)

    def close(self) -> None:
        self.gateway.close()
        self.events.stop()

    def _on_error(self, event) -> None:
        if not self.ready.is_set():
            self.error = event.data
            self.ready.set()
