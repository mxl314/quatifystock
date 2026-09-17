from __future__ import annotations

from datetime import datetime, timedelta

from ..core.models import Bar
from ..strategy.pivot import PivotDetector
from .models import ChartBar, PivotMarker


def detect_pivots(
    contract: str,
    bars: tuple[ChartBar, ...],
    interval_seconds: int,
) -> tuple[PivotMarker, ...]:
    """Run the trading strategy's detector over completed chart bars."""
    detector = PivotDetector(contract, interval_seconds)
    markers: list[PivotMarker] = []
    for chart_bar in bars:
        if not chart_bar.complete:
            continue
        start = datetime.fromisoformat(chart_bar.time)
        signal = detector.update(Bar(
            contract=contract,
            interval_seconds=interval_seconds,
            start_time=start,
            end_time=start + timedelta(seconds=interval_seconds),
            open_price=chart_bar.open,
            high_price=chart_bar.high,
            low_price=chart_bar.low,
            close_price=chart_bar.close,
            volume=chart_bar.volume,
            open_interest=chart_bar.open_interest,
        ))
        if signal is not None:
            markers.append(PivotMarker(
                time=signal.pivot.start_time.isoformat(),
                price=(
                    signal.pivot.low_price
                    if signal.kind == "bottom"
                    else signal.pivot.high_price
                ),
                confirmation_time=signal.confirmation.start_time.isoformat(),
                confirmation_price=signal.confirmation.close_price,
                kind=signal.kind,
                label="底部拐点" if signal.kind == "bottom" else "顶部拐点",
            ))
    return tuple(markers)


def detect_bottom_pivots(
    contract: str,
    bars: tuple[ChartBar, ...],
    interval_seconds: int,
) -> tuple[PivotMarker, ...]:
    """Compatibility helper returning only bottom pivots."""
    return tuple(
        marker for marker in detect_pivots(contract, bars, interval_seconds)
        if marker.kind == "bottom"
    )
