from __future__ import annotations

import argparse
import threading

from quant_framework.adapters.ctp import CtpConfig, CtpMarketGateway


def main() -> None:
    parser = argparse.ArgumentParser(description="订阅 SimNow CTP 实时行情")
    parser.add_argument("contract", help="统一合约，例如 DCE|F|P|2701")
    parser.add_argument("--config", default="config/ctp.example.toml")
    args = parser.parse_args()

    ready = threading.Event()
    gateway: CtpMarketGateway

    def on_event(event) -> None:
        if event.type == "gateway.ready":
            gateway.subscribe(args.contract)
            ready.set()
        elif event.type in {"tick", "gateway.error"}:
            print(event.data)

    gateway = CtpMarketGateway(on_event, CtpConfig.from_toml(args.config))
    try:
        gateway.connect()
        if not ready.wait(15):
            raise TimeoutError("15 秒内未完成 CTP 行情登录")
        while True:
            threading.Event().wait(1)
    except KeyboardInterrupt:
        pass
    finally:
        gateway.close()


if __name__ == "__main__":
    main()
