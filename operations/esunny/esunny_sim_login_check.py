"""Login-only operational check against the configured Esunny V10 simulation front."""

from __future__ import annotations

import queue
import time
from pathlib import Path

from quant_framework.adapters.esunny import V10Config, V10NativeGateway


def main() -> int:
    config = V10Config.from_toml(Path("config/esunny.toml"))
    if not config.account or not config.password or not config.app_id:
        raise RuntimeError("登录测试缺少账号、密码或 AppId")
    if (config.account != "Q1062383955" or config.front_ip != "123.161.206.213"
            or config.front_port != 6668 or config.live_trading):
        raise RuntimeError("配置不是预期的模拟账号、模拟前置或下单闸门已开启")
    events: queue.Queue = queue.Queue()
    gateway = V10NativeGateway(events.put, config)
    try:
        gateway.connect()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                event = events.get(timeout=min(1, deadline - time.monotonic()))
            except queue.Empty:
                continue
            if event.type == "gateway.login":
                data = event.data
                print("login_result", {"account": data.get("account"),
                                       "error_code": data.get("error_code"),
                                       "trade_date": data.get("trade_date")}, flush=True)
                return 0 if data.get("account") == config.account and data.get("error_code") == 0 else 2
            if event.type in {"gateway.error", "gateway.disconnected"}:
                print("gateway_result", {"type": event.type, "data": event.data}, flush=True)
                return 2
        print("login_timeout: no login callback in 30s", flush=True)
        return 2
    finally:
        gateway.close()


if __name__ == "__main__":
    raise SystemExit(main())
