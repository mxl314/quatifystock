from __future__ import annotations

import argparse
import threading

from esunny_quant.events import EventBus
from esunny_quant.gateway.v10_quote import V10QuoteGateway
from esunny_quant.quote_client import QuoteClient
from esunny_quant.quote_config import QuoteConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="获取易盛 V10 实时行情")
    parser.add_argument("contract", help="完整合约号，可先从 quote.contract 事件中查询")
    parser.add_argument("--config", default="config/quote.toml")
    parser.add_argument("--count", type=int, default=10)
    args = parser.parse_args()

    bus = EventBus()
    done = threading.Event()
    received = 0

    def on_tick(event) -> None:
        nonlocal received
        received += 1
        print(event.data)
        if received >= args.count:
            done.set()

    bus.subscribe("tick", on_tick)
    bus.subscribe("quote.error", lambda event: print("行情错误:", event.data))
    config = QuoteConfig.from_toml(args.config)
    client = QuoteClient(lambda sink: V10QuoteGateway(sink, config), event_bus=bus)
    try:
        client.connect()
        client.subscribe(args.contract)
        if not done.wait(60):
            raise TimeoutError("60 秒内未收到足够行情，请检查合约号和交易时段")
    finally:
        client.close()


if __name__ == "__main__":
    main()
