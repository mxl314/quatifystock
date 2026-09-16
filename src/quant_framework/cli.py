from __future__ import annotations

import argparse
import dataclasses
import importlib
import json
import os
import threading
import time
from pathlib import Path

from .adapters.ctp import CtpConfig, CtpMarketGateway, CtpTradingGateway
from .adapters.esunny import QuoteConfig, V10Config, V10NativeGateway, V10QuoteGateway
from .adapters.mock import MockGateway, MockQuoteGateway
from .core import Event, EventBus, Tick
from .runtime import LiveRuntime
from .services import TradingEngine
from .storage import SQLiteTickStore
from .strategy import FiveMinutePivotStrategy, Strategy


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="模块化 Python 期货交易框架")
    parser.add_argument("--gateway", choices=("mock", "v10", "ctp"), default="mock")
    parser.add_argument("--config", help="配置文件；易盛默认 config/esunny.toml，CTP 默认 config/ctp.toml")
    parser.add_argument("--response-timeout", type=float, default=10.0, help="等待查询或委托回报的秒数")
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("buy", "sell", "close-long", "close-short"):
        cmd = sub.add_parser(action)
        cmd.add_argument("--contract", required=True)
        cmd.add_argument("--price", required=True, type=float)
        cmd.add_argument("--volume", required=True, type=int)
        cmd.add_argument("--contract-index", type=int, default=0, help="易盛合约索引；CTP 会忽略")
    sub.add_parser("funds")
    sub.add_parser("positions")
    run = sub.add_parser("run", help="统一启动行情、交易、存储和策略")
    run.add_argument("--contract", action="append", required=True,
                     help="订阅的统一合约号；可重复指定")
    run.add_argument("--strategy", action="append", required=True,
                     help="five-minute-pivot 或 Python模块:策略类；可重复指定")
    run.add_argument("--trading-day", required=True, help="Tick 归属交易日 YYYY-MM-DD")
    run.add_argument("--database", default="data/market_ticks.sqlite3")
    run.add_argument("--quote-config", default="config/quote.toml",
                     help="易盛行情配置；CTP 使用 --config")
    run.add_argument("--bar-interval", action="append", type=int,
                     help="K线周期秒数；可重复指定，默认 300")
    run.add_argument("--run-seconds", type=float, default=0,
                     help="运行秒数；0 表示持续到 Ctrl+C")
    run.add_argument("--heartbeat-seconds", type=float, default=5,
                     help="运行心跳打印间隔秒数；0 表示关闭，默认 5")
    run.add_argument("--execute", action="store_true",
                     help="允许策略发单；仍需对应网关确认环境变量")
    return parser


def _config_path(value: str | None, default: str) -> Path:
    path = Path(value or default)
    if not path.is_file():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    return path


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.action == "run":
        return _run_live(args)
    bus = EventBus()
    ready = threading.Event()
    response = threading.Event()

    def on_event(event: Event) -> None:
        _print_event(event)
        if event.type in {"order", "fund", "position.end"}:
            response.set()
        elif event.type == "position" and isinstance(event.data, dict) and event.data.get("last"):
            response.set()

    bus.subscribe("gateway.ready", lambda _event: ready.set())
    for kind in ("order", "trade", "fund", "position", "position.end", "gateway.error"):
        bus.subscribe(kind, on_event)

    if args.gateway == "mock":
        factory = lambda sink: MockGateway(sink)
    elif args.gateway == "ctp":
        config = CtpConfig.from_toml(_config_path(args.config, "config/ctp.toml"))
        factory = lambda sink: CtpTradingGateway(sink, config)
    else:
        config = V10Config.from_toml(_config_path(args.config, "config/esunny.toml"))
        factory = lambda sink: V10NativeGateway(sink, config)

    engine = TradingEngine(factory, event_bus=bus)
    try:
        engine.connect()
        if not ready.wait(30):
            raise TimeoutError("等待 API Ready 超时")
        if args.action == "funds":
            engine.query_funds()
        elif args.action == "positions":
            engine.query_positions()
        else:
            fn = getattr(engine, args.action.replace("-", "_"))
            client_id = fn(
                args.contract,
                args.price,
                args.volume,
                contract_index=args.contract_index,
            )
            print(json.dumps(
                {"client_order_id": client_id, "status": engine.orders[client_id].status.value},
                ensure_ascii=False,
            ))
        if not response.wait(args.response_timeout):
            raise TimeoutError(f"{args.response_timeout:g} 秒内未收到操作回报")
        return 0
    finally:
        engine.close()


def _print_event(event: Event) -> None:
    print(json.dumps({"event": event.type, "data": event.data}, ensure_ascii=False, default=str))


def _run_live(args) -> int:
    if args.heartbeat_seconds < 0:
        raise ValueError("--heartbeat-seconds 不能小于 0")
    market_factory, trading_factory = _live_factories(args)
    store = SQLiteTickStore(args.database, args.trading_day, batch_size=500)
    runtime = LiveRuntime(
        market_factory,
        trading_factory,
        bar_intervals=tuple(args.bar_interval or (300,)),
        tick_store=store,
        tick_flush_seconds=60,
    )
    for index, spec in enumerate(args.strategy, 1):
        runtime.add_strategy(f"{spec}-{index}", _load_strategy(spec, args.contract, args.execute))
    live_events = threading.Event()
    stats_lock = threading.Lock()
    tick_count = 0
    latest_ticks: dict[str, dict[str, object]] = {}

    def collect_tick(event: Event) -> None:
        nonlocal tick_count
        tick = event.data
        if not isinstance(tick, Tick):
            return
        with stats_lock:
            tick_count += 1
            latest_ticks[tick.contract] = {
                "last_price": tick.last_price,
                "exchange_time": str(tick.timestamp),
            }

    runtime.events.subscribe("tick", collect_tick)

    def print_live_event(event: Event) -> None:
        if event.type in {"gateway.error", "quote.error"} or live_events.is_set():
            _print_event(event)
    for event_type in ("gateway.error", "quote.error", "order", "trade"):
        runtime.events.subscribe(event_type, print_live_event)

    try:
        runtime.connect(timeout=30)
        live_events.set()
        for contract in args.contract:
            runtime.subscribe(contract)
        print(json.dumps({
            "status": "running", "gateway": args.gateway,
            "contracts": args.contract, "strategies": args.strategy,
            "database": str(Path(args.database).resolve()),
            "execute": args.execute,
        }, ensure_ascii=False), flush=True)
        started_at = time.monotonic()
        deadline = started_at + args.run_seconds if args.run_seconds > 0 else None
        next_heartbeat = started_at + args.heartbeat_seconds
        while deadline is None or time.monotonic() < deadline:
            now = time.monotonic()
            if args.heartbeat_seconds > 0 and now >= next_heartbeat:
                with stats_lock:
                    current_count = tick_count
                    current_ticks = dict(latest_ticks)
                print(json.dumps({
                    "status": "heartbeat",
                    "uptime_seconds": round(now - started_at, 1),
                    "tick_count": current_count,
                    "latest_ticks": current_ticks,
                }, ensure_ascii=False), flush=True)
                next_heartbeat = now + args.heartbeat_seconds
            sleep_seconds = 0.2
            if deadline is not None:
                sleep_seconds = min(sleep_seconds, max(0, deadline - now))
            time.sleep(sleep_seconds)
    except KeyboardInterrupt:
        print(json.dumps({"status": "stopping"}, ensure_ascii=False), flush=True)
    finally:
        runtime.close()
    return 0


def _live_factories(args):
    if args.gateway == "mock":
        return (
            lambda sink: MockQuoteGateway(sink),
            lambda sink: MockGateway(sink, auto_fill=True),
        )
    if args.gateway == "ctp":
        config = CtpConfig.from_toml(_config_path(args.config, "config/ctp.toml"))
        config = dataclasses.replace(config, live_trading=args.execute)
        if args.execute and os.getenv("CTP_LIVE_CONFIRM") != "I_UNDERSTAND":
            raise PermissionError("--execute 还需要 CTP_LIVE_CONFIRM=I_UNDERSTAND")
        return (
            lambda sink: CtpMarketGateway(sink, config),
            lambda sink: CtpTradingGateway(sink, config),
        )

    trading = V10Config.from_toml(_config_path(args.config, "config/esunny.toml"))
    if not trading.license_no and trading.app_id == "Demo_TestCollect":
        trading = dataclasses.replace(trading, license_no="Demo_TestCollect")
    trading = dataclasses.replace(trading, live_trading=args.execute)
    if args.execute and os.getenv("ESUNNY_LIVE_CONFIRM") != "I_UNDERSTAND":
        raise PermissionError("--execute 还需要 ESUNNY_LIVE_CONFIRM=I_UNDERSTAND")
    quote = QuoteConfig.from_toml(_config_path(args.quote_config, "config/quote.toml"))
    return (
        lambda sink: V10QuoteGateway(sink, quote),
        lambda sink: V10NativeGateway(sink, trading),
    )


def _load_strategy(spec: str, contracts: list[str], execute: bool) -> Strategy:
    if spec == "five-minute-pivot":
        if len(contracts) != 1:
            raise ValueError("five-minute-pivot 当前要求只订阅一个合约")
        return FiveMinutePivotStrategy(contracts[0], execute=execute)
    module_name, separator, attribute = spec.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("策略格式应为 five-minute-pivot 或 Python模块:策略类")
    strategy_type = getattr(importlib.import_module(module_name), attribute)
    strategy = strategy_type()
    if not isinstance(strategy, Strategy):
        raise TypeError(f"{spec} 不是 Strategy 实例")
    return strategy


if __name__ == "__main__":
    raise SystemExit(main())
