from __future__ import annotations

import argparse
import json
import threading

from .config import V10Config
from .engine import TradingEngine
from .events import EventBus
from .gateway.mock import MockGateway
from .gateway.v10_native import V10NativeGateway
from .models import Event


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="易盛 V10 Python 交易框架")
    parser.add_argument("--gateway", choices=("mock", "v10"), default="mock")
    parser.add_argument("--config", default="config/esunny.toml")
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("buy", "sell", "close-long", "close-short"):
        cmd = sub.add_parser(action)
        cmd.add_argument("--contract", required=True)
        cmd.add_argument("--price", required=True, type=float)
        cmd.add_argument("--volume", required=True, type=int)
        cmd.add_argument("--contract-index", type=int, default=0)
    sub.add_parser("funds")
    sub.add_parser("positions")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    bus = EventBus()
    ready = threading.Event()
    bus.subscribe("gateway.ready", lambda _e: ready.set())
    for kind in ("order", "trade", "fund", "position", "gateway.error"):
        bus.subscribe(kind, _print_event)
    if args.gateway == "mock":
        factory = lambda sink: MockGateway(sink)
    else:
        config = V10Config.from_toml(args.config)
        factory = lambda sink: V10NativeGateway(sink, config)
    engine = TradingEngine(factory, event_bus=bus)
    engine.connect()
    if not ready.wait(30):
        raise TimeoutError("等待 API Ready 超时")
    if args.action == "funds":
        engine.query_funds()
    elif args.action == "positions":
        engine.query_positions()
    else:
        fn = getattr(engine, args.action.replace("-", "_"))
        client_id = fn(args.contract, args.price, args.volume, contract_index=args.contract_index)
        print(json.dumps({"client_order_id": client_id, "status": engine.orders[client_id].status.value}, ensure_ascii=False))
    return 0


def _print_event(event: Event) -> None:
    print(json.dumps({"event": event.type, "data": event.data}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    raise SystemExit(main())

