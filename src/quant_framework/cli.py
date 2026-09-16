from __future__ import annotations

import argparse
import dataclasses
import importlib
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from .adapters.ctp import CtpConfig, CtpMarketGateway, CtpTradingGateway
from .adapters.esunny import QuoteConfig, V10Config, V10NativeGateway, V10QuoteGateway
from .adapters.mock import MockGateway, MockQuoteGateway
from .core import Event, EventBus, Tick
from .runtime import LiveRuntime
from .services.chart_feed import LiveChartFeed
from .services import OrderStorageService, TradingEngine
from .storage import SQLiteOrderStore, SQLiteTickStore
from .strategy import PivotStrategy, Strategy
from .visualization import (
    ChartData,
    DatabaseChartProvider,
    LiveChartServer,
    SQLiteChartRepository,
    write_chart_report,
)


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
        cmd.add_argument("--database", default="data/market_ticks.sqlite3")
        cmd.add_argument("--trading-day", help="订单归属交易日；默认使用本地日期")
    sub.add_parser("funds")
    sub.add_parser("positions")
    run = sub.add_parser("run", help="统一启动行情、交易、存储和策略")
    run.add_argument("--contract", action="append", required=True,
                     help="订阅的统一合约号；可重复指定")
    run.add_argument("--strategy", action="append", required=True,
                     help="pivot:周期秒数、five-minute-pivot 或 Python模块:策略类；可重复指定")
    run.add_argument("--trading-day", required=True, help="Tick 归属交易日 YYYY-MM-DD")
    run.add_argument("--database", default="data/market_ticks.sqlite3")
    run.add_argument("--quote-config", default="config/quote.toml",
                     help="易盛行情配置；CTP 使用 --config")
    run.add_argument("--bar-interval", action="append", type=int,
                     help="K线周期秒数；可重复指定，默认 300")
    run.add_argument("--run-seconds", type=float, default=0,
                     help="运行秒数；0 表示持续到 Ctrl+C")
    run.add_argument("--heartbeat-seconds", type=float, default=60,
                     help="运行心跳打印间隔秒数；0 表示关闭，默认 60")
    run.add_argument("--chart-host", default="127.0.0.1",
                     help="盘中图表监听地址，默认仅本机访问")
    run.add_argument("--chart-port", type=int, default=0,
                     help="盘中实时图表端口；0 表示不启动，建议 8765")
    run.add_argument("--execute", action="store_true",
                     help="允许策略发单；仍需对应网关确认环境变量")
    for action, help_text in (
        ("chart-live", "启动读取SQLite的盘中K线网页"),
        ("chart-report", "生成盘后K线HTML报告"),
    ):
        chart = sub.add_parser(action, help=help_text)
        chart.add_argument("--database", default="data/market_ticks.sqlite3")
        chart.add_argument("--contract", required=True)
        chart.add_argument("--trading-day", help="默认读取该合约最新交易日")
        chart.add_argument("--interval", type=int, default=300, help="K线周期秒数")
        if action == "chart-live":
            chart.add_argument("--host", default="127.0.0.1")
            chart.add_argument("--port", type=int, default=8765)
        else:
            chart.add_argument("--output", help="输出HTML路径")
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
    if args.action == "chart-live":
        return _chart_live(args)
    if args.action == "chart-report":
        return _chart_report(args)
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
    order_storage = None
    if args.action in {"buy", "sell", "close-long", "close-short"}:
        trading_day = args.trading_day or datetime.now().astimezone().date().isoformat()
        order_storage = OrderStorageService(
            bus, SQLiteOrderStore(args.database), gateway=args.gateway,
            account=_storage_account(args), trading_day=trading_day,
        )
        order_storage.start()
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
        try:
            engine.close()
        finally:
            if order_storage:
                order_storage.close()


def _print_event(event: Event) -> None:
    print(json.dumps({"event": event.type, "data": event.data}, ensure_ascii=False, default=str))


def _run_live(args) -> int:
    if args.heartbeat_seconds < 0:
        raise ValueError("--heartbeat-seconds 不能小于 0")
    market_factory, trading_factory = _live_factories(args)
    store = SQLiteTickStore(args.database, args.trading_day, batch_size=500)
    order_store = SQLiteOrderStore(args.database)
    strategy_intervals = tuple(
        interval for spec in args.strategy
        if (interval := _pivot_interval(spec)) is not None
    )
    bar_intervals = list(args.bar_interval or ())
    for interval in strategy_intervals:
        if interval not in bar_intervals:
            bar_intervals.append(interval)
    if not bar_intervals:
        bar_intervals.append(300)
    runtime = LiveRuntime(
        market_factory,
        trading_factory,
        bar_intervals=tuple(bar_intervals),
        tick_store=store,
        tick_flush_seconds=60,
        order_store=order_store,
        gateway_name=args.gateway,
        account=_storage_account(args),
        trading_day=args.trading_day,
    )
    strategy_instances: list[str] = []
    for index, spec in enumerate(args.strategy, 1):
        for instance_name, strategy in _load_strategies(
            spec, args.contract, args.execute,
        ):
            runtime_name = f"{instance_name}-{index}"
            runtime.add_strategy(runtime_name, strategy)
            strategy_instances.append(runtime_name)
    chart_feed = None
    chart_server = None
    if args.chart_port:
        if len(args.contract) != 1:
            raise ValueError("盘中图表当前要求只订阅一个合约")
        interval = bar_intervals[0]
        try:
            initial = SQLiteChartRepository(args.database).load(
                args.contract[0], interval, args.trading_day,
            )
        except (LookupError, FileNotFoundError):
            initial = ChartData(args.contract[0], args.trading_day, interval, ())
        chart_feed = LiveChartFeed(
            runtime.events, args.contract[0], args.trading_day, interval,
            initial=initial,
        )
        chart_server = LiveChartServer(
            chart_feed, host=args.chart_host, port=args.chart_port,
        )
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
        if chart_feed:
            chart_feed.start()
        runtime.connect(timeout=30)
        live_events.set()
        for contract in args.contract:
            runtime.subscribe(contract)
        if chart_server:
            chart_server.start()
        print(json.dumps({
            "status": "running", "gateway": args.gateway,
            "contracts": args.contract, "strategies": args.strategy,
            "strategy_instances": strategy_instances,
            "database": str(Path(args.database).resolve()),
            "execute": args.execute,
            "chart_url": chart_server.url if chart_server else None,
            "chart_queue_capacity": chart_feed.queue_capacity if chart_feed else None,
            "storage_queue_capacity": (
                runtime.tick_storage.queue_capacity if runtime.tick_storage else None
            ),
            "order_queue_capacity": (
                runtime.order_storage.queue_capacity if runtime.order_storage else None
            ),
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
                heartbeat = {
                    "status": "heartbeat",
                    "uptime_seconds": round(now - started_at, 1),
                    "tick_count": current_count,
                    "latest_ticks": current_ticks,
                }
                if chart_feed:
                    heartbeat.update({
                        "chart_queue_size": chart_feed.queued_events,
                        "chart_dropped_events": chart_feed.dropped_events,
                    })
                if runtime.tick_storage:
                    heartbeat.update({
                        "storage_queue_size": runtime.tick_storage.queued_events,
                        "storage_persisted_rows": runtime.tick_storage.persisted_rows,
                        "storage_dropped_events": runtime.tick_storage.dropped_events,
                        "storage_failed_events": (
                            runtime.tick_storage.failed_events
                            + runtime.tick_storage.failed_flushes
                        ),
                    })
                if runtime.order_storage:
                    heartbeat.update({
                        "order_queue_size": runtime.order_storage.queued_events,
                        "orders_persisted": runtime.order_storage.persisted_orders,
                        "trades_persisted": runtime.order_storage.persisted_trades,
                        "order_storage_dropped_events": runtime.order_storage.dropped_events,
                        "order_storage_failed_events": runtime.order_storage.failed_events,
                    })
                print(json.dumps(heartbeat, ensure_ascii=False), flush=True)
                next_heartbeat = now + args.heartbeat_seconds
            sleep_seconds = 0.2
            if deadline is not None:
                sleep_seconds = min(sleep_seconds, max(0, deadline - now))
            time.sleep(sleep_seconds)
    except KeyboardInterrupt:
        print(json.dumps({"status": "stopping"}, ensure_ascii=False), flush=True)
    finally:
        try:
            runtime.close()
        finally:
            try:
                if chart_feed:
                    chart_feed.close()
            finally:
                if chart_server:
                    chart_server.close()
    return 0


def _chart_report(args) -> int:
    data = SQLiteChartRepository(args.database).load(
        args.contract, args.interval, args.trading_day,
    )
    symbol = args.contract.replace("|", "_").replace("/", "_")
    output = args.output or f"reports/{symbol}_{data.trading_day}_{args.interval}s.html"
    path = write_chart_report(data, output)
    print(json.dumps({
        "status": "created", "report": str(path),
        "bars": len(data.bars), "trades": len(data.trades),
    }, ensure_ascii=False), flush=True)
    return 0


def _chart_live(args) -> int:
    provider = DatabaseChartProvider(
        args.database, args.contract, args.interval, args.trading_day,
    )
    initial = provider.snapshot()
    server = LiveChartServer(provider, host=args.host, port=args.port)
    try:
        server.start()
        print(json.dumps({
            "status": "running", "chart_url": server.url,
            "bars": len(initial.bars), "source": str(Path(args.database).resolve()),
        }, ensure_ascii=False), flush=True)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(json.dumps({"status": "stopping"}, ensure_ascii=False), flush=True)
    finally:
        server.close()
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


def _storage_account(args) -> str:
    if args.gateway == "mock":
        return "mock"
    if args.gateway == "ctp":
        return CtpConfig.from_toml(
            _config_path(args.config, "config/ctp.toml"),
        ).user_id
    return V10Config.from_toml(
        _config_path(args.config, "config/esunny.toml"),
    ).account


def _load_strategies(
    spec: str, contracts: list[str], execute: bool,
) -> tuple[tuple[str, Strategy], ...]:
    pivot_interval = _pivot_interval(spec)
    if pivot_interval is not None:
        return tuple(
            (
                f"{spec}:{contract}",
                PivotStrategy(
                    contract, pivot_interval, execute=execute,
                ),
            )
            for contract in contracts
        )
    module_name, separator, attribute = spec.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError(
            "策略格式应为 pivot:周期秒数、five-minute-pivot 或 Python模块:策略类",
        )
    strategy_type = getattr(importlib.import_module(module_name), attribute)
    strategy = strategy_type()
    if not isinstance(strategy, Strategy):
        raise TypeError(f"{spec} 不是 Strategy 实例")
    return ((spec, strategy),)


def _pivot_interval(spec: str) -> int | None:
    if spec == "five-minute-pivot":
        return 300
    if not spec.startswith("pivot:"):
        return None
    value = spec.removeprefix("pivot:")
    try:
        interval = int(value)
    except ValueError as exc:
        raise ValueError("pivot 策略周期必须是正整数秒数，例如 pivot:60") from exc
    if interval <= 0:
        raise ValueError("pivot 策略周期必须大于 0")
    return interval


if __name__ == "__main__":
    raise SystemExit(main())
