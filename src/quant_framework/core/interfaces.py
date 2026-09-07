from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

from .models import Event, OrderRequest

EventSink = Callable[[Event], None]


@dataclass(frozen=True, slots=True)
class AdapterCapabilities:
    market_data: bool = False
    trading: bool = False
    market_order: bool = False
    native_condition_order: bool = False
    historical_data: bool = False


class TradingGateway(ABC):
    def __init__(self, event_sink: EventSink) -> None:
        self.emit = event_sink

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def send_order(self, request_id: int, order: OrderRequest) -> None: ...

    @abstractmethod
    def cancel_order(self, request_id: int, order_id: int, system_no: str = "") -> None: ...

    @abstractmethod
    def query_funds(self) -> None: ...

    @abstractmethod
    def query_positions(self) -> None: ...


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
