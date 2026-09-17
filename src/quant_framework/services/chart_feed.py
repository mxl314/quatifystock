from __future__ import annotations

import logging
import queue
import threading
from dataclasses import replace
from datetime import datetime, timedelta
from enum import Enum

from ..core.events import EventBus
from ..core.models import Event, Tick, Trade
from ..services.bar_builder import tick_datetime
from ..visualization.models import ChartBar, ChartData, TradeMarker
from ..visualization.pivots import detect_pivots


class LiveChartFeed:
    """Build chart snapshots on a worker fed by non-blocking event callbacks."""

    def __init__(
        self,
        event_bus: EventBus,
        contract: str,
        trading_day: str,
        interval_seconds: int,
        *,
        initial: ChartData | None = None,
        queue_size: int = 10_000,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds 必须大于 0")
        if queue_size <= 0:
            raise ValueError("queue_size 必须大于 0")
        self.contract = contract
        self.trading_day = trading_day
        self.interval_seconds = interval_seconds
        self._lock = threading.Lock()
        self._queue: queue.Queue[Event | None] = queue.Queue(maxsize=queue_size)
        self._thread: threading.Thread | None = None
        self._log = logging.getLogger(__name__)
        self.dropped_events = 0
        self._bars = {bar.time: bar for bar in (initial.bars if initial else ())}
        self._trades = list(initial.trades if initial else ())
        self._latest_start = max(self._bars, default=None)
        self._first_tick_times = {
            key: datetime.fromisoformat(key) for key in self._bars
        }
        self._last_tick_times = dict(self._first_tick_times)
        self._previous_total_volume: int | None = None
        self.late_tick_events = 0
        event_bus.subscribe("tick", self._enqueue)
        event_bus.subscribe("trade", self._enqueue)

    @property
    def queued_events(self) -> int:
        return self._queue.qsize()

    @property
    def queue_capacity(self) -> int:
        return self._queue.maxsize

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, name="chart-feed", daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        if self._thread is None:
            return
        self._queue.put(None)
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            self._log.error("图表队列未能在5秒内排空")
        self._thread = None

    def snapshot(self) -> ChartData:
        with self._lock:
            bars = tuple(self._bars.values())
            trades = tuple(self._trades)
        bars = tuple(sorted(bars, key=lambda value: value.time))
        return ChartData(
            contract=self.contract,
            trading_day=self.trading_day,
            interval_seconds=self.interval_seconds,
            bars=bars,
            trades=trades,
            pivots=detect_pivots(
                self.contract, bars, self.interval_seconds,
            ),
        )

    def _enqueue(self, event: Event) -> None:
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            self.dropped_events += 1

    def _run(self) -> None:
        while True:
            event = self._queue.get()
            if event is None:
                return
            try:
                if event.type == "tick":
                    self._process_tick(event)
                elif event.type == "trade":
                    self._process_trade(event)
            except Exception:
                self._log.exception("图表事件处理失败: %s", event.type)

    def _process_tick(self, event: Event) -> None:
        tick = event.data
        if not isinstance(tick, Tick) or tick.contract != self.contract:
            return
        timestamp = tick_datetime(tick.timestamp)
        start = self._floor(timestamp).isoformat()
        with self._lock:
            if self._latest_start is not None and start < self._latest_start:
                self.late_tick_events += 1
                return
            previous = self._bars.get(start)
            if previous is not None and previous.complete:
                self.late_tick_events += 1
                return
            advanced = self._latest_start is not None and start > self._latest_start
            if self._latest_start is None or advanced:
                self._latest_start = start
            for bar_time, existing in tuple(self._bars.items()):
                if bar_time < start and not existing.complete:
                    self._bars[bar_time] = replace(existing, complete=True)
            volume_delta = self._volume_delta(
                tick, reset_on_decrease=advanced,
            )
            if previous is None:
                self._first_tick_times[start] = timestamp
                self._last_tick_times[start] = timestamp
                self._bars[start] = ChartBar(
                    time=start, open=tick.last_price, high=tick.last_price,
                    low=tick.last_price, close=tick.last_price,
                    volume=volume_delta, open_interest=tick.open_interest,
                    complete=False,
                )
            else:
                first_tick_time = self._first_tick_times.get(start, timestamp)
                last_tick_time = self._last_tick_times.get(start, timestamp)
                open_price = previous.open
                close_price = previous.close
                if timestamp < first_tick_time:
                    first_tick_time = timestamp
                    open_price = tick.last_price
                if timestamp >= last_tick_time:
                    last_tick_time = timestamp
                    close_price = tick.last_price
                self._first_tick_times[start] = first_tick_time
                self._last_tick_times[start] = last_tick_time
                self._bars[start] = ChartBar(
                    time=start, open=open_price,
                    high=max(previous.high, tick.last_price),
                    low=min(previous.low, tick.last_price), close=close_price,
                    volume=previous.volume + volume_delta,
                    open_interest=tick.open_interest,
                    complete=False,
                )

    def _process_trade(self, event: Event) -> None:
        data = event.data
        if isinstance(data, Trade):
            contract, side, offset, volume, price = (
                data.contract, data.side, data.offset, data.volume, data.price,
            )
        elif isinstance(data, dict):
            contract = str(data.get("contract", ""))
            side, offset = data.get("side", ""), data.get("offset", "")
            volume, price = int(data.get("volume", 0)), float(data.get("price", 0))
        else:
            return
        if contract != self.contract:
            return
        side_text, offset_text = self._text(side), self._text(offset)
        marker = TradeMarker(
            time=event.created_at.astimezone().isoformat(), price=price,
            side=side_text, offset=offset_text, volume=volume,
            label=f"{self._side_label(side_text)} {volume}@{price:g}",
        )
        with self._lock:
            self._trades.append(marker)

    def _floor(self, timestamp: datetime) -> datetime:
        origin = datetime(1970, 1, 1, tzinfo=timestamp.tzinfo)
        elapsed = int((timestamp - origin).total_seconds())
        return origin + timedelta(
            seconds=elapsed - elapsed % self.interval_seconds,
        )

    def _volume_delta(self, tick: Tick, *, reset_on_decrease: bool = False) -> int:
        previous = self._previous_total_volume
        if tick.total_volume:
            if previous is None:
                self._previous_total_volume = tick.total_volume
            elif tick.total_volume >= previous:
                self._previous_total_volume = tick.total_volume
                return tick.total_volume - previous
            elif reset_on_decrease:
                self._previous_total_volume = tick.total_volume
                return max(0, tick.last_volume)
            else:
                return 0
        return max(0, tick.last_volume)

    @staticmethod
    def _text(value: object) -> str:
        return str(value.value if isinstance(value, Enum) else value)

    @staticmethod
    def _side_label(value: str) -> str:
        return "买" if value.lower() in {"b", "buy"} or "买" in value else "卖"
