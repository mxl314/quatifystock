from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Side(str, Enum):
    BUY = "B"
    SELL = "S"


class Offset(str, Enum):
    OPEN = "O"
    CLOSE = "C"
    CLOSE_TODAY = "T"


class Hedge(str, Enum):
    SPECULATION = "T"
    HEDGE = "B"


class OrderType(str, Enum):
    MARKET = "1"
    LIMIT = "2"


class TimeInForce(str, Enum):
    FOK = "1"
    IOC = "2"
    GFD = "3"
    GIS = "4"


class OrderStatus(str, Enum):
    SUBMITTING = "submitting"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class OrderRequest:
    contract: str
    side: Side
    offset: Offset
    volume: int
    price: float
    contract_index: int = 0
    hedge: Hedge = Hedge.SPECULATION
    order_type: OrderType = OrderType.LIMIT
    time_in_force: TimeInForce = TimeInForce.GFD
    min_volume: int = 0
    seat_index: int = 0
    reference: int | None = None

    def __post_init__(self) -> None:
        if not self.contract.strip():
            raise ValueError("contract 不能为空")
        if self.volume <= 0:
            raise ValueError("volume 必须大于 0")
        if self.price <= 0 and self.order_type is OrderType.LIMIT:
            raise ValueError("限价单 price 必须大于 0")
        if self.min_volume < 0 or self.min_volume > self.volume:
            raise ValueError("min_volume 必须在 0..volume 之间")


@dataclass(slots=True)
class Order:
    client_order_id: str
    request_id: int
    request: OrderRequest
    status: OrderStatus = OrderStatus.SUBMITTING
    traded_volume: int = 0
    order_id: int = 0
    system_no: str = ""
    error_code: int = 0
    message: str = ""
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True, slots=True)
class Trade:
    trade_id: str
    order_id: int
    contract: str
    side: Side
    offset: Offset
    volume: int
    price: float
    fee: float = 0.0


@dataclass(frozen=True, slots=True)
class Tick:
    contract: str
    last_price: float
    bid_price: float = 0.0
    ask_price: float = 0.0
    bid_volume: int = 0
    ask_volume: int = 0
    timestamp: int = 0


@dataclass(frozen=True, slots=True)
class Event:
    type: str
    data: Any
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

