"""在易盛模拟盘监测 P2701，确认连续完整 5 分钟 K 线底拐点后只报一手买开。"""

from __future__ import annotations

import argparse
import dataclasses
import os
import queue
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_framework.adapters.esunny import QuoteConfig, V10Config, V10NativeGateway, V10QuoteGateway
from quant_framework.core.enums import Offset, Side
from quant_framework.core.models import OrderRequest
from quant_framework.services.bar_builder import BarBuilder, tick_datetime
from quant_framework.strategy.pivot import FiveMinuteBottomPivot


ACCOUNT = "Q1062383955"
TRADE_CONTRACT = "P2701"
QUOTE_CONTRACT = "DCE|F|P|2701"
SIM_FRONT = "123.161.206.213"
SHANGHAI = timezone(timedelta(hours=8))


def _wait_for(events: queue.Queue, target: str, seconds: float) -> dict:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            event = events.get(timeout=min(1, deadline - time.monotonic()))
        except queue.Empty:
            continue
        if event.type in {"gateway.error", "gateway.disconnected", "quote.error", "quote.disconnected"}:
            raise RuntimeError(f"网关错误：{event.type}: {event.data}")
        if event.type == "gateway.login" and event.data.get("error_code") != 0:
            raise RuntimeError(f"交易登录失败，代码 {event.data.get('error_code')}")
        if event.type == target:
            return event.data
    raise TimeoutError(f"等待 {target} 超时")


def _fresh(tick) -> bool:
    when = tick_datetime(tick.timestamp)
    if when.tzinfo is None:
        when = when.replace(tzinfo=SHANGHAI)
    age = (datetime.now(timezone.utc) - when.astimezone(timezone.utc)).total_seconds()
    return -2 <= age <= 10


def _order_reply(events: queue.Queue, request_id: int, seconds: float) -> dict | None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            event = events.get(timeout=min(1, deadline - time.monotonic()))
        except queue.Empty:
            continue
        if event.type in {"gateway.error", "gateway.disconnected"}:
            raise RuntimeError(f"报单后网关错误：{event.data}；订单状态需人工核查")
        if event.type == "order" and int(event.data.get("request_id", -1)) == request_id:
            return event.data
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="确认仅向易盛模拟前置报单")
    parser.add_argument("--max-wait-minutes", type=int, default=30)
    args = parser.parse_args()
    if not args.execute or os.getenv("ESUNNY_LIVE_CONFIRM") != "I_UNDERSTAND":
        raise PermissionError("需要 --execute 和 ESUNNY_LIVE_CONFIRM=I_UNDERSTAND")
    if args.max_wait_minutes < 16 or args.max_wait_minutes > 120:
        raise ValueError("等待时间必须在 16..120 分钟")

    cfg = V10Config.from_toml(Path("config/esunny.toml"))
    if cfg.account != ACCOUNT or cfg.front_ip != SIM_FRONT or cfg.front_port != 6668:
        raise RuntimeError("账号或交易前置与已核对的模拟环境不一致，停止报单")
    if not cfg.license_no and cfg.app_id == "Demo_TestCollect":
        cfg = dataclasses.replace(cfg, license_no="Demo_TestCollect")
    cfg.assert_credentials()
    cfg = dataclasses.replace(cfg, live_trading=True)
    quote_cfg = QuoteConfig(Path("build/native/esunny_v10_quote_bridge.dll"))
    trade_events: queue.Queue = queue.Queue()
    quote_events: queue.Queue = queue.Queue()
    trade = V10NativeGateway(trade_events.put, cfg)
    quote = V10QuoteGateway(quote_events.put, quote_cfg)
    try:
        trade.connect()
        login = _wait_for(trade_events, "gateway.login", 25)
        if login.get("account") != ACCOUNT:
            raise RuntimeError("登录回报账号不匹配")
        contract_index = 0
        ready = False
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            event = trade_events.get(timeout=max(0.1, deadline - time.monotonic()))
            if event.type in {"gateway.error", "gateway.disconnected"}:
                raise RuntimeError(f"交易网关错误：{event.data}")
            if event.type == "contract" and event.data.get("contract") == TRADE_CONTRACT:
                index = int(event.data.get("contract_index", 0))
                if contract_index and index != contract_index:
                    raise RuntimeError("合约索引冲突")
                contract_index = index
            if event.type == "gateway.ready":
                ready = True
            if ready and contract_index > 0:
                break
        else:
            raise TimeoutError("交易 API 未就绪或未取得 P2701 合约索引")
        trade.query_funds()
        fund = _wait_for(trade_events, "fund", 10)
        if fund.get("account") != ACCOUNT or float(fund.get("available", 0)) <= 0:
            raise RuntimeError("资金账户不匹配或可用资金非正数")

        quote.connect()
        _wait_for(quote_events, "quote.ready", 15)
        quote.subscribe(QUOTE_CONTRACT)
        builder = BarBuilder(300)
        detector = FiveMinuteBottomPivot(QUOTE_CONTRACT)
        warmup = True
        first_tick = None
        last_tick = None
        working_start = None
        deadline = time.monotonic() + args.max_wait_minutes * 60
        print("monitoring", {"contract": QUOTE_CONTRACT, "max_wait_minutes": args.max_wait_minutes}, flush=True)
        while time.monotonic() < deadline:
            try:
                event = quote_events.get(timeout=1)
            except queue.Empty:
                continue
            if event.type in {"quote.error", "quote.disconnected"}:
                raise RuntimeError(f"行情网关错误：{event.data}")
            if event.type != "tick" or event.data.contract != QUOTE_CONTRACT:
                continue
            tick = event.data
            if tick.last_price <= 0 or not _fresh(tick):
                continue
            timestamp = tick_datetime(tick.timestamp)
            start = builder._floor(timestamp)
            previous_first, previous_last = first_tick, last_tick
            if start != working_start:
                working_start = start
                first_tick = timestamp
            last_tick = timestamp
            bar = builder.update(tick)
            if bar is None:
                continue
            if warmup:
                warmup = False  # 首根由订阅时刻开始，可能不是完整 K 线。
                continue
            if (previous_first is None or previous_last is None
                    or previous_first > bar.start_time + timedelta(seconds=60)
                    or previous_last < bar.end_time - timedelta(seconds=60)):
                print("bar_skipped: insufficient tick coverage", flush=True)
                continue
            print("bar", {"start": bar.start_time.isoformat(), "high": bar.high_price,
                          "low": bar.low_price, "close": bar.close_price}, flush=True)
            signal = detector.update(bar)
            if signal is None:
                continue
            if time.monotonic() >= deadline or not _fresh(tick):
                raise RuntimeError("信号出现时行情已过期")
            price = tick.ask_price if tick.ask_price > 0 else tick.last_price
            if price <= 0 or (tick.upper_limit > 0 and price > tick.upper_limit) or (
                    tick.lower_limit > 0 and price < tick.lower_limit):
                raise RuntimeError("报单价格无效")
            print("pivot_confirmed", {"pivot_low": signal.pivot.low_price,
                                      "confirmation_close": signal.confirmation.close_price,
                                      "limit_price": price}, flush=True)
            trade.query_funds()
            fund = _wait_for(trade_events, "fund", 10)
            if fund.get("account") != ACCOUNT or float(fund.get("available", 0)) <= 0:
                raise RuntimeError("报单前资金核验失败")
            request_id = int(time.time()) % 1_000_000_000
            order = OrderRequest(TRADE_CONTRACT, Side.BUY, Offset.OPEN, 1, price,
                                 contract_index=contract_index)
            trade.send_order(request_id, order)
            print("submitted", {"contract": TRADE_CONTRACT, "volume": 1,
                                "price": price, "request_id": request_id}, flush=True)
            result = _order_reply(trade_events, request_id, 15)
            if result is None:
                print("result_unknown: no order callback; do not retry", flush=True)
                return 2
            print("order_result", result, flush=True)
            return 0
        print("timeout: no confirmed pivot; no order", flush=True)
        return 1
    finally:
        quote.close()
        trade.close()


if __name__ == "__main__":
    raise SystemExit(main())
