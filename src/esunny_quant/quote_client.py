from __future__ import annotations

import threading

from .events import EventBus
from .gateway.quote_base import MarketDataGateway


class QuoteClient:
    def __init__(self, gateway_factory, *, event_bus: EventBus | None = None) -> None:
        self.events = event_bus or EventBus()
        self.gateway: MarketDataGateway = gateway_factory(self.events.publish)
        self.ready = threading.Event()
        self.events.subscribe("quote.ready", lambda _event: self.ready.set())

    def connect(self, timeout: float = 30) -> None:
        self.gateway.connect()
        if not self.ready.wait(timeout):
            raise TimeoutError("等待易盛行情 API Ready 超时")

    def subscribe(self, *contracts: str) -> None:
        for contract in contracts:
            self.gateway.subscribe(contract)

    def unsubscribe(self, *contracts: str) -> None:
        for contract in contracts:
            self.gateway.unsubscribe(contract)

    def close(self) -> None:
        self.gateway.close()
        self.events.stop()

