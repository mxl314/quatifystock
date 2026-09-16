"""Collect P2701 ticks into one long-lived SQLite database."""

from __future__ import annotations

import argparse
import queue
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_framework.adapters.esunny import QuoteConfig, V10QuoteGateway
from quant_framework.storage import SQLiteTickStore


CONTRACT = "DCE|F|P|2701"
CHINA_TIME = timezone(timedelta(hours=8))


def main() -> int:
    parser = argparse.ArgumentParser(description="把 p2701 Tick 持续写入统一 SQLite 数据库")
    parser.add_argument(
        "--trading-day",
        default=datetime.now(CHINA_TIME).date().isoformat(),
        help="交易日 YYYY-MM-DD；夜盘应填写其归属的下一交易日",
    )
    parser.add_argument("--database", default="data/market_ticks.sqlite3")
    parser.add_argument("--batch-size", type=int, default=500,
                        help="累计多少条 Tick 后提交，默认 500")
    parser.add_argument("--flush-seconds", type=float, default=60,
                        help="最长提交间隔秒数，默认 60")
    parser.add_argument(
        "--duration-seconds", type=int, default=0,
        help="采集秒数；0 表示持续到 Ctrl+C",
    )
    args = parser.parse_args()
    if args.duration_seconds < 0:
        raise ValueError("duration-seconds 不能小于 0")
    if args.batch_size <= 0 or args.flush_seconds <= 0:
        raise ValueError("batch-size 和 flush-seconds 必须大于 0")

    events: queue.Queue = queue.Queue()
    config = QuoteConfig(
        Path("build/native/esunny_v10_quote_bridge.dll"),
        "123.161.206.213", 6161, Path("logs/quote"),
    )
    gateway = V10QuoteGateway(events.put, config)
    store = SQLiteTickStore(args.database, args.trading_day, batch_size=args.batch_size)
    before = store.count(CONTRACT)
    received = 0
    deadline = (time.monotonic() + args.duration_seconds
                if args.duration_seconds else None)
    try:
        gateway.connect()
        ready_deadline = time.monotonic() + 15
        while time.monotonic() < ready_deadline:
            try:
                event = events.get(timeout=min(1, ready_deadline - time.monotonic()))
            except queue.Empty:
                continue
            if event.type == "quote.ready":
                break
            if event.type in {"quote.error", "quote.disconnected"}:
                raise RuntimeError(f"行情连接失败：{event.data}")
        else:
            raise TimeoutError("15 秒内易盛行情 API 未就绪")

        gateway.subscribe(CONTRACT)
        print({"status": "collecting", "contract": CONTRACT,
               "trading_day": args.trading_day,
               "batch_size": args.batch_size,
               "flush_seconds": args.flush_seconds,
               "database": str(Path(args.database).resolve())}, flush=True)
        next_flush = time.monotonic() + args.flush_seconds
        while deadline is None or time.monotonic() < deadline:
            timeout = min(1, max(0.01, deadline - time.monotonic())) if deadline else 1
            try:
                event = events.get(timeout=timeout)
            except queue.Empty:
                event = None
            if event is not None:
                if event.type in {"quote.error", "quote.disconnected"}:
                    raise RuntimeError(f"行情中断：{event.data}")
                if event.type == "tick" and event.data.contract == CONTRACT:
                    store.append(event.data)
                    received += 1
            if time.monotonic() >= next_flush:
                store.flush()
                next_flush = time.monotonic() + args.flush_seconds
    except KeyboardInterrupt:
        print("收到 Ctrl+C，停止采集。", flush=True)
    finally:
        gateway.close()
        store.close()

    # Reopen after the final commit so the summary also proves the DB is readable.
    with SQLiteTickStore(args.database, args.trading_day) as check:
        after = check.count(CONTRACT)
        day_count = check.count(CONTRACT, args.trading_day)
    print({"status": "stopped", "received": received,
           "new_unique_ticks": after - before,
           "contract_total_ticks": after,
           "trading_day_ticks": day_count}, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
