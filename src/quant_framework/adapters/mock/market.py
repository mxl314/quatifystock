from __future__ import annotations

from ...core.models import Event
from ...core.models import MarketTick
from ...core.interfaces import EventSink
from ...core.interfaces import MarketDataGateway


class MockQuoteGateway(MarketDataGateway):
    def __init__(self, event_sink: EventSink) -> None:
        super().__init__(event_sink)
        self.connected = False
        self.subscriptions: set[str] = set()

    def connect(self) -> None:
        self.connected = True
        self.emit(Event("quote.ready", {}))

    def close(self) -> None:
        self.connected = False

    def subscribe(self, contract: str) -> None:
        if not self.connected:
            raise RuntimeError("行情网关未连接")
        self.subscriptions.add(contract)

    def unsubscribe(self, contract: str) -> None:
        self.subscriptions.discard(contract)

    def query_contracts(self) -> None:
        self.emit(Event("quote.contract", {"contract": "ZCE|F|SR|701", "is_last": True}))

    def push_tick(self, contract: str, last_price: float) -> None:
        if contract not in self.subscriptions:
            return
        self.emit(Event("tick", MarketTick(
            contract=contract, timestamp=0, last_price=last_price, last_volume=1,
            bid_price=last_price - 1, bid_volume=10, ask_price=last_price + 1,
            ask_volume=12, open_price=last_price, high_price=last_price,
            low_price=last_price, pre_settlement=last_price, upper_limit=last_price * 1.1,
            lower_limit=last_price * 0.9, total_volume=1, open_interest=100,
        )))

