from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..core.events import EventBus
from ..core.models import Event, Tick, TimelinePoint
from .bar_builder import tick_datetime


@dataclass(slots=True)
class _TimelineState:
    day: object
    total_amount: float = 0.0
    total_volume: int = 0
    last_total_volume: int = 0


class TimelineService:
    """生成逐 Tick 分时点及当日成交量加权均价。"""

    def __init__(self, event_bus: EventBus) -> None:
        self.events = event_bus
        self._states: dict[str, _TimelineState] = {}
        event_bus.subscribe("tick", self._on_tick)

    def _on_tick(self, event: Event) -> None:
        tick: Tick = event.data
        timestamp: datetime = tick_datetime(tick.timestamp)
        state = self._states.get(tick.contract)
        if state is None or state.day != timestamp.date():
            state = _TimelineState(timestamp.date())
            self._states[tick.contract] = state
        if tick.total_volume and state.last_total_volume:
            delta = max(0, tick.total_volume - state.last_total_volume)
        else:
            delta = max(0, tick.last_volume)
        if tick.total_volume:
            state.last_total_volume = tick.total_volume
        state.total_amount += tick.last_price * delta
        state.total_volume += delta
        average = state.total_amount / state.total_volume if state.total_volume else tick.last_price
        self.events.publish(Event("timeline", TimelinePoint(
            contract=tick.contract,
            timestamp=timestamp,
            price=tick.last_price,
            average_price=average,
            volume=state.total_volume,
        )))
