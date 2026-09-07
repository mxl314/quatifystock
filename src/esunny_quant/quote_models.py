from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MarketTick:
    contract: str
    timestamp: int
    last_price: float
    last_volume: int
    bid_price: float
    bid_volume: int
    ask_price: float
    ask_volume: int
    open_price: float
    high_price: float
    low_price: float
    pre_settlement: float
    upper_limit: float
    lower_limit: float
    total_volume: int
    open_interest: int

