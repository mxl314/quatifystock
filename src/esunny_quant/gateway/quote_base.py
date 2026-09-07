from __future__ import annotations

from abc import ABC, abstractmethod

from .base import EventSink


class MarketDataGateway(ABC):
    def __init__(self, event_sink: EventSink) -> None:
        self.emit = event_sink

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def subscribe(self, contract: str) -> None: ...

    @abstractmethod
    def unsubscribe(self, contract: str) -> None: ...

    @abstractmethod
    def query_contracts(self) -> None: ...

