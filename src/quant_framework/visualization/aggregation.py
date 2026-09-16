from __future__ import annotations

from collections.abc import Iterable

from ..core.models import Bar, Tick
from ..services.bar_builder import BarBuilder
from .models import ChartBar


def aggregate_ticks(ticks: Iterable[Tick], interval_seconds: int) -> tuple[ChartBar, ...]:
    """Aggregate ordered ticks and include the unfinished final bar."""
    builder = BarBuilder(interval_seconds)
    bars: list[tuple[Bar, bool]] = []
    for tick in ticks:
        completed = builder.update(tick)
        if completed is not None:
            bars.append((completed, True))
    bars.extend((bar, False) for bar in builder.flush())
    bars.sort(key=lambda value: value[0].start_time)
    return tuple(
        ChartBar(
            time=bar.start_time.isoformat(),
            open=bar.open_price,
            high=bar.high_price,
            low=bar.low_price,
            close=bar.close_price,
            volume=bar.volume,
            open_interest=bar.open_interest,
            complete=complete,
        )
        for bar, complete in bars
    )
