from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..core.events import EventBus
from ..core.models import Bar, Event, Tick


def tick_datetime(value: str | int | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    if value:
        seconds = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    return datetime.now(tz=timezone.utc)


@dataclass(slots=True)
class _WorkingBar:
    start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    open_interest: int


class BarBuilder:
    """按自然时间边界将标准 Tick 聚合为 OHLCV K线。"""

    def __init__(self, interval_seconds: int = 60) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds 必须大于 0")
        self.interval_seconds = interval_seconds
        self._bars: dict[str, _WorkingBar] = {}
        self._total_volume: dict[str, int] = {}

    def update(self, tick: Tick) -> Bar | None:
        timestamp = tick_datetime(tick.timestamp)
        start = self._floor(timestamp)
        delta = self._volume_delta(tick)
        current = self._bars.get(tick.contract)
        completed = None
        if current is not None and current.start != start:
            completed = self._finish(tick.contract, current)
            current = None
        if current is None:
            self._bars[tick.contract] = _WorkingBar(
                start, tick.last_price, tick.last_price, tick.last_price,
                tick.last_price, delta, tick.open_interest,
            )
        else:
            current.high = max(current.high, tick.last_price)
            current.low = min(current.low, tick.last_price)
            current.close = tick.last_price
            current.volume += delta
            current.open_interest = tick.open_interest
        return completed

    def flush(self) -> list[Bar]:
        bars = [self._finish(contract, value) for contract, value in self._bars.items()]
        self._bars.clear()
        return bars

    def _floor(self, timestamp: datetime) -> datetime:
        origin = datetime(1970, 1, 1, tzinfo=timestamp.tzinfo)
        elapsed = int((timestamp - origin).total_seconds())
        return origin + timedelta(seconds=elapsed - elapsed % self.interval_seconds)

    def _volume_delta(self, tick: Tick) -> int:
        previous = self._total_volume.get(tick.contract)
        self._total_volume[tick.contract] = tick.total_volume
        if tick.total_volume and previous is not None and tick.total_volume >= previous:
            return tick.total_volume - previous
        return max(0, tick.last_volume)

    def _finish(self, contract: str, value: _WorkingBar) -> Bar:
        return Bar(
            contract=contract,
            interval_seconds=self.interval_seconds,
            start_time=value.start,
            end_time=value.start + timedelta(seconds=self.interval_seconds),
            open_price=value.open,
            high_price=value.high,
            low_price=value.low,
            close_price=value.close,
            volume=value.volume,
            open_interest=value.open_interest,
        )


class BarService:
    def __init__(self, event_bus: EventBus, intervals: tuple[int, ...] = (60,)) -> None:
        self.events = event_bus
        self.builders = [BarBuilder(interval) for interval in intervals]
        event_bus.subscribe("tick", self._on_tick)

    def flush(self) -> None:
        for builder in self.builders:
            for bar in builder.flush():
                self.events.publish(Event("bar", bar))

    def _on_tick(self, event: Event) -> None:
        for builder in self.builders:
            bar = builder.update(event.data)
            if bar is not None:
                self.events.publish(Event("bar", bar))
