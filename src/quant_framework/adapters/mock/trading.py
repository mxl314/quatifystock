from __future__ import annotations

from dataclasses import asdict
from itertools import count

from ...core.models import Event, OrderRequest, OrderStatus, Trade
from ...core.interfaces import EventSink, TradingGateway


class MockGateway(TradingGateway):
    """确定性模拟网关；auto_fill=True 时订单立即全成。"""

    def __init__(self, event_sink: EventSink, *, auto_fill: bool = True) -> None:
        super().__init__(event_sink)
        self.auto_fill = auto_fill
        self.connected = False
        self.orders: dict[int, dict] = {}
        self._order_ids = count(100001)

    def connect(self) -> None:
        self.connected = True
        self.emit(Event("gateway.ready", {"gateway": "mock"}))

    def close(self) -> None:
        self.connected = False
        self.emit(Event("gateway.disconnected", {"gateway": "mock"}))

    def send_order(self, request_id: int, order: OrderRequest) -> None:
        if not self.connected:
            raise RuntimeError("mock 网关未连接")
        order_id = next(self._order_ids)
        self.orders[order_id] = {"request_id": request_id, "request": order, "cancelled": False}
        self.emit(Event("order", {
            "request_id": request_id, "order_id": order_id, "system_no": f"MOCK{order_id}",
            "status": OrderStatus.ACCEPTED.value, "traded_volume": 0, "error_code": 0,
        }))
        if self.auto_fill:
            self.emit(Event("trade", asdict(Trade(
                trade_id=f"T{order_id}", order_id=order_id, contract=order.contract,
                side=order.side, offset=order.offset, volume=order.volume, price=order.price,
            ))))
            self.emit(Event("order", {
                "request_id": request_id, "order_id": order_id, "system_no": f"MOCK{order_id}",
                "status": OrderStatus.FILLED.value, "traded_volume": order.volume, "error_code": 0,
            }))

    def cancel_order(self, request_id: int, order_id: int, system_no: str = "") -> None:
        record = self.orders.get(order_id)
        if not record:
            raise KeyError(f"未找到订单 {order_id}")
        record["cancelled"] = True
        self.emit(Event("order", {
            "request_id": record["request_id"], "order_id": order_id,
            "system_no": system_no or f"MOCK{order_id}", "status": OrderStatus.CANCELLED.value,
            "traded_volume": 0, "error_code": 0,
        }))

    def query_funds(self) -> None:
        self.emit(Event("fund", {"account": "mock", "equity": 1_000_000.0, "available": 1_000_000.0}))

    def query_positions(self) -> None:
        self.emit(Event("position.end", None))

