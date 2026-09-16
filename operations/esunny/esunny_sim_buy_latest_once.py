"""One-shot Esunny V10 simulation buy using a fresh last-traded quote."""

from __future__ import annotations

import dataclasses
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from quant_framework.adapters.esunny import QuoteConfig, V10Config, V10NativeGateway, V10QuoteGateway
from quant_framework.core.enums import Offset, Side
from quant_framework.core.models import OrderRequest


ACCOUNT = "Q1062383955"
TRADE_CONTRACT = "P2701"
QUOTE_CONTRACT = "DCE|F|P|2701"
FRONT = "123.161.206.213"


def main() -> int:
    if os.getenv("ESUNNY_ACCOUNT") and os.getenv("ESUNNY_ACCOUNT") != ACCOUNT:
        raise RuntimeError("环境变量账号与模拟账号不一致")
    if os.getenv("ESUNNY_LIVE_CONFIRM") != "I_UNDERSTAND":
        raise RuntimeError("下单确认闸门未开启")

    trade_ready = threading.Event()
    contract_ready = threading.Event()
    fund_ready = threading.Event()
    quote_ready = threading.Event()
    tick_ready = threading.Event()
    order_seen = threading.Event()
    trade_seen = threading.Event()
    state: dict[str, object] = {"contracts": [], "orders": [], "trades": []}

    def on_trade(event) -> None:
        kind, data = event.type, event.data
        if kind == "gateway.login":
            state["login"] = data
            print("login", data, flush=True)
        elif kind == "gateway.ready":
            trade_ready.set()
            print("trade_ready", data, flush=True)
        elif kind == "contract":
            if data.get("contract") == TRADE_CONTRACT:
                state["contracts"].append(data)
                contract_ready.set()
                print("trade_contract", data, flush=True)
        elif kind == "fund":
            state["fund"] = data
            fund_ready.set()
            print("fund", data, flush=True)
        elif kind == "order":
            if state.get("submitted") and data.get("request_id") == state.get("request_id"):
                state["orders"].append(data)
                order_seen.set()
                print("order", data, flush=True)
        elif kind == "trade":
            if state.get("submitted") and data.get("contract") == TRADE_CONTRACT:
                state["trades"].append(data)
                trade_seen.set()
                print("trade", data, flush=True)
        elif kind in {"gateway.error", "gateway.disconnected"}:
            print(kind, data, flush=True)

    def on_quote(event) -> None:
        kind, data = event.type, event.data
        if kind == "quote.ready":
            quote_ready.set()
        elif kind == "tick" and data.contract == QUOTE_CONTRACT:
            state["tick"] = data
            state["tick_seen_at"] = time.monotonic()
            tick_ready.set()
        elif kind in {"quote.error", "quote.disconnected"}:
            print(kind, data, flush=True)

    base_cfg = V10Config.from_toml(Path("config/esunny.toml"))
    if base_cfg.account != ACCOUNT or base_cfg.front_ip != FRONT or base_cfg.front_port != 6668:
        raise RuntimeError("配置不是已验证的模拟账号或模拟交易前置")
    if not base_cfg.license_no and base_cfg.app_id == "Demo_TestCollect":
        base_cfg = dataclasses.replace(base_cfg, license_no="Demo_TestCollect")
    base_cfg.assert_credentials()
    trade_cfg = dataclasses.replace(base_cfg, live_trading=True)
    quote_cfg = QuoteConfig(
        Path("build/native/esunny_v10_quote_bridge.dll"), FRONT, 6161, Path("logs/quote")
    )
    trade_gateway = V10NativeGateway(on_trade, trade_cfg)
    quote_gateway = V10QuoteGateway(on_quote, quote_cfg)
    try:
        trade_gateway.connect()
        if not trade_ready.wait(25):
            raise TimeoutError("交易 API 未就绪")
        login = state.get("login")
        if not isinstance(login, dict) or login.get("error_code") != 0:
            raise RuntimeError("交易登录未确认成功")
        if not contract_ready.wait(10):
            raise TimeoutError("交易柜台未返回 P2701 索引")
        contracts = state["contracts"]
        if len(contracts) != 1 or contracts[0].get("contract_index", 0) <= 0:
            raise RuntimeError("P2701 索引不唯一或无效")
        contract_index = int(contracts[0]["contract_index"])

        fund_ready.clear()
        trade_gateway.query_funds()
        if not fund_ready.wait(10):
            raise TimeoutError("资金查询无回报")
        fund = state["fund"]
        if fund.get("account") != ACCOUNT:
            raise RuntimeError("资金账户不匹配")

        quote_gateway.connect()
        if not quote_ready.wait(15):
            raise TimeoutError("行情 API 未就绪")
        quote_gateway.subscribe(QUOTE_CONTRACT)
        if not tick_ready.wait(15):
            raise TimeoutError("没有收到 P2701 行情")
        tick = state["tick"]
        tick_age = time.monotonic() - state["tick_seen_at"]
        quote_age = abs((datetime.now() - datetime.fromisoformat(tick.timestamp)).total_seconds())
        if tick_age > 2 or quote_age > 10:
            raise RuntimeError(f"行情不够新：接收延迟 {tick_age:.1f}s，成交时间差 {quote_age:.1f}s")
        price = float(tick.last_price)
        if price <= 0 or not tick.lower_limit <= price <= tick.upper_limit:
            raise RuntimeError("最新价无效或超出涨跌停范围")
        if float(fund.get("available", 0)) <= 0:
            raise RuntimeError("可用资金非正数")

        request_id = int(time.time()) % 1_000_000_000
        order = OrderRequest(
            TRADE_CONTRACT, Side.BUY, Offset.OPEN, 1, price, contract_index=contract_index
        )
        print(
            "submit", {"account": ACCOUNT, "quote_contract": QUOTE_CONTRACT,
                       "trade_contract": TRADE_CONTRACT, "contract_index": contract_index,
                       "volume": 1, "price": price, "quote_time": tick.timestamp},
            flush=True,
        )
        state["request_id"] = request_id
        state["submitted"] = True
        trade_gateway.send_order(request_id, order)
        if not order_seen.wait(15) and not trade_seen.is_set():
            print("result_unknown: no order callback within 15s; do not retry", flush=True)
            return 2
        trade_seen.wait(15)
        print("final", {"orders": state["orders"], "trades": state["trades"]}, flush=True)
        return 3 if any(o.get("status") == "rejected" for o in state["orders"]) else 0
    finally:
        quote_gateway.close()
        trade_gateway.close()


if __name__ == "__main__":
    raise SystemExit(main())
