from __future__ import annotations

import threading
from itertools import count
from uuid import uuid4

from ..core.events import EventBus
from ..core.interfaces import TradingGateway
from ..core.models import Event, Offset, Order, OrderRequest, OrderStatus, Side
from .risk import RiskManager


class TradingEngine:
    def __init__(self, gateway_factory, *, risk: RiskManager | None = None, event_bus: EventBus | None = None) -> None:
        self.events = event_bus or EventBus()
        self.risk = risk or RiskManager()
        self.gateway: TradingGateway = gateway_factory(self.events.publish)
        self.orders: dict[str, Order] = {}
        self._by_request: dict[int, str] = {}
        self._by_reference: dict[int, str] = {}
        self._request_ids = count(1)
        self._lock = threading.RLock()
        self.events.subscribe("order", self._on_order)
        self.events.subscribe("tick", self._on_tick)

    def connect(self) -> None:
        self.gateway.connect()

    def close(self) -> None:
        self.gateway.close()
        self.events.stop()

    def submit(self, request: OrderRequest) -> str:
        self.risk.check(request)
        request_id = next(self._request_ids)
        reference = request.reference if request.reference is not None else request_id
        client_order_id = uuid4().hex
        order = Order(client_order_id, request_id, request)
        with self._lock:
            self.orders[client_order_id] = order
            self._by_request[request_id] = client_order_id
            self._by_reference[reference] = client_order_id
            self.risk.on_submitted(request)
        try:
            self.gateway.send_order(request_id, request)
        except Exception:
            with self._lock:
                order.status = OrderStatus.REJECTED
                self.risk.on_terminal()
            raise
        return client_order_id

    def buy(self, contract: str, price: float, volume: int, **kwargs) -> str:
        return self.submit(OrderRequest(contract, Side.BUY, Offset.OPEN, volume, price, **kwargs))

    def sell(self, contract: str, price: float, volume: int, **kwargs) -> str:
        return self.submit(OrderRequest(contract, Side.SELL, Offset.OPEN, volume, price, **kwargs))

    def close_long(self, contract: str, price: float, volume: int, **kwargs) -> str:
        return self.submit(OrderRequest(contract, Side.SELL, Offset.CLOSE, volume, price, **kwargs))

    def close_short(self, contract: str, price: float, volume: int, **kwargs) -> str:
        return self.submit(OrderRequest(contract, Side.BUY, Offset.CLOSE, volume, price, **kwargs))

    def cancel(self, client_order_id: str) -> None:
        order = self.orders[client_order_id]
        request_id = next(self._request_ids)
        self._by_request[request_id] = client_order_id
        self.gateway.cancel_order(request_id, order.order_id, order.system_no)

    def query_funds(self) -> None:
        self.gateway.query_funds()

    def query_positions(self) -> None:
        self.gateway.query_positions()

    def _on_tick(self, event: Event) -> None:
        data = event.data
        contract = data.contract if hasattr(data, "contract") else data["contract"]
        price = data.last_price if hasattr(data, "last_price") else data["last_price"]
        self.risk.last_prices[contract] = price

    def _on_order(self, event: Event) -> None:
        data = event.data
        key = int(data.get("request_id", 0))
        client_id = self._by_request.get(key) or self._by_reference.get(key)
        if not client_id:
            return
        order = self.orders[client_id]
        previous = order.status
        order.order_id = int(data.get("order_id", order.order_id))
        order.system_no = str(data.get("system_no", order.system_no))
        order.traded_volume = int(data.get("traded_volume", order.traded_volume))
        order.error_code = int(data.get("error_code", 0))
        order.message = str(data.get("message", order.message))
        order.status = OrderStatus(data.get("status", OrderStatus.UNKNOWN.value))
        terminal = {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}
        if previous not in terminal and order.status in terminal:
            self.risk.on_terminal()

