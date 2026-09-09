from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path

from .adapters.ctp import CtpConfig, CtpTradingGateway
from .adapters.esunny import V10Config, V10NativeGateway
from .adapters.mock import MockGateway
from .core import Event, EventBus
from .services import TradingEngine


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
    return parser


def _config_path(value: str | None, default: str) -> Path:
    path = Path(value or default)
    if not path.is_file():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    return path


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
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


if __name__ == "__main__":
    raise SystemExit(main())
