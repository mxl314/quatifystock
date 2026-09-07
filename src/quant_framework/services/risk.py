from __future__ import annotations

from dataclasses import dataclass, field

from ..core.models import OrderRequest


class RiskRejected(RuntimeError):
    pass


@dataclass(slots=True)
class RiskLimits:
    max_order_volume: int = 10
    max_daily_volume: int = 100
    max_active_orders: int = 20
    max_price_deviation_pct: float = 0.05
    allowed_contracts: set[str] = field(default_factory=set)


class RiskManager:
    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()
        self.daily_volume = 0
        self.active_orders = 0
        self.last_prices: dict[str, float] = {}
        self.kill_switch = False

    def check(self, order: OrderRequest) -> None:
        if self.kill_switch:
            raise RiskRejected("风控急停已启用")
        if order.volume > self.limits.max_order_volume:
            raise RiskRejected("超过单笔最大手数")
        if self.daily_volume + order.volume > self.limits.max_daily_volume:
            raise RiskRejected("超过当日累计最大手数")
        if self.active_orders >= self.limits.max_active_orders:
            raise RiskRejected("活动委托数已达上限")
        if self.limits.allowed_contracts and order.contract not in self.limits.allowed_contracts:
            raise RiskRejected("合约不在白名单")
        last = self.last_prices.get(order.contract)
        if last and abs(order.price - last) / last > self.limits.max_price_deviation_pct:
            raise RiskRejected("委托价偏离最新价过大")

    def on_submitted(self, order: OrderRequest) -> None:
        self.daily_volume += order.volume
        self.active_orders += 1

    def on_terminal(self) -> None:
        self.active_orders = max(0, self.active_orders - 1)

