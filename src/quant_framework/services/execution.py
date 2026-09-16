from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime, timezone
from enum import Enum
from itertools import count
from uuid import uuid4

from ..core.events import EventBus
from ..core.interfaces import TradingGateway
from ..core.models import Event, Offset, Order, OrderRequest, OrderStatus, Side, Trade
from .risk import RiskManager


class TradingEngine:
    def __init__(self, gateway_factory, *, risk: RiskManager | None = None, event_bus: EventBus | None = None) -> None:
        self.events = event_bus or EventBus()
        self.risk = risk or RiskManager()
        self.gateway: TradingGateway = gateway_factory(self.events.publish)
        self.orders: dict[str, Order] = {}
        self._by_request: dict[int, str] = {}
        self._by_reference: dict[int, str] = {}
        self._by_order_id: dict[int, str] = {}
        self._request_ids = count(1)
        self._lock = threading.RLock()
        self.events.subscribe("order", self._on_order)
        self.events.subscribe("trade", self._on_trade)
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
        self._publish_order_snapshot(order)
        try:
            self.gateway.send_order(request_id, request)
        except Exception as exc:
            with self._lock:
                order.status = OrderStatus.REJECTED
                order.message = str(exc)
                order.updated_at = datetime.now(timezone.utc)
                self.risk.on_terminal()
            self._publish_order_snapshot(order)
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
        if order.order_id:
            self._by_order_id[order.order_id] = client_id
        order.system_no = str(data.get("system_no", order.system_no))
        order.traded_volume = int(data.get("traded_volume", order.traded_volume))
        order.error_code = int(data.get("error_code", 0))
        order.message = str(data.get("message", order.message))
        order.status = OrderStatus(data.get("status", OrderStatus.UNKNOWN.value))
        order.updated_at = event.created_at
        terminal = {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}
        if previous not in terminal and order.status in terminal:
            self.risk.on_terminal()
        self._publish_order_snapshot(order, created_at=event.created_at)

    def _on_trade(self, event: Event) -> None:
        data = event.data
        if isinstance(data, Trade):
            raw = {
                "trade_id": data.trade_id, "order_id": data.order_id,
                "contract": data.contract, "side": data.side,
                "offset": data.offset, "volume": data.volume,
                "price": data.price, "fee": data.fee,
            }
        elif isinstance(data, dict):
            raw = data
        else:
            return
        order_id = int(raw.get("order_id", 0))
        client_id = self._by_order_id.get(order_id, "")
        order = self.orders.get(client_id)
        side = order.request.side if order else raw.get("side", "")
        offset = order.request.offset if order else raw.get("offset", "")
        contract = order.request.contract if order else str(raw.get("contract", ""))
        trade_time = raw.get("trade_time") or raw.get("match_time")
        if not trade_time:
            trade_time = event.created_at.astimezone().isoformat()
        normalized = {
            "client_order_id": client_id,
            "trade_id": str(raw.get("trade_id", "")),
            "order_id": order_id,
            "contract": contract,
            "side": self._enum_value(side),
            "offset": self._enum_value(offset),
            "volume": int(raw.get("volume", 0)),
            "price": float(raw.get("price", 0)),
            "fee": float(raw.get("fee", 0)),
            "trade_time": str(trade_time),
            "received_at": event.created_at.isoformat(),
        }
        normalized["label"] = self._trade_label(
            normalized["side"], normalized["offset"],
        )
        self.events.publish(Event("trade.normalized", normalized, event.created_at))

    def _publish_order_snapshot(
        self, order: Order, *, created_at: datetime | None = None,
    ) -> None:
        self.events.publish(Event(
            "order.snapshot", replace(order), created_at or order.updated_at,
        ))

    @staticmethod
    def _enum_value(value: object) -> str:
        return str(value.value if isinstance(value, Enum) else value)

    @staticmethod
    def _trade_label(side: str, offset: str) -> str:
        side_label = "买" if side == Side.BUY.value else "卖"
        offset_label = {
            Offset.OPEN.value: "开",
            Offset.CLOSE.value: "平",
            Offset.CLOSE_TODAY.value: "平今",
        }.get(offset, offset)
        return side_label + offset_label
