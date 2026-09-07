from enum import Enum


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
