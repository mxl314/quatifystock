"""Close the verified P2701 simulation long position using a fresh bid quote."""

from __future__ import annotations

import dataclasses
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from quant_framework.adapters.esunny import (
    QuoteConfig,
    V10Config,
    V10NativeGateway,
    V10QuoteGateway,
)
from quant_framework.core import Event, EventBus, OrderStatus
from quant_framework.services import OrderStorageService, TradingEngine
from quant_framework.storage import SQLiteOrderStore


ACCOUNT = "Q1062383955"
TRADE_CONTRACT = "P2701"
QUOTE_CONTRACT = "DCE|F|P|2701"
FRONT = "123.161.206.213"
DATABASE = Path("data/market_ticks.sqlite3")


def main() -> int:
    if os.getenv("ESUNNY_ACCOUNT") and os.getenv("ESUNNY_ACCOUNT") != ACCOUNT:
        raise RuntimeError("环境变量账号与模拟账号不一致")
    if os.getenv("ESUNNY_LIVE_CONFIRM") != "I_UNDERSTAND":
        raise RuntimeError("下单确认闸门未开启")

    ready = threading.Event()
    fund_ready = threading.Event()
    position_end = threading.Event()
    quote_ready = threading.Event()
    tick_ready = threading.Event()
    order_terminal = threading.Event()
    state: dict[str, object] = {}

    bus = EventBus()

    def on_event(event: Event) -> None:
        if event.type == "gateway.login":
            state["login"] = event.data
        elif event.type == "gateway.ready":
            ready.set()
        elif event.type == "contract" and event.data.get("contract") == TRADE_CONTRACT:
            state["contract"] = event.data
        elif event.type == "fund":
            state["fund"] = event.data
            fund_ready.set()
        elif event.type == "position" and event.data.get("contract") == TRADE_CONTRACT:
            state["position"] = event.data
        elif event.type == "position.end":
            position_end.set()
        elif event.type == "quote.ready":
            quote_ready.set()
        elif event.type == "tick" and event.data.contract == QUOTE_CONTRACT:
            state["tick"] = event.data
            state["tick_seen_at"] = time.monotonic()
            tick_ready.set()
        elif event.type == "order.snapshot":
            order = event.data
            if order.client_order_id == state.get("client_order_id"):
                state["order"] = order
                if order.status in {
                    OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELLED,
                }:
                    order_terminal.set()
        elif event.type == "trade.normalized":
            if event.data.get("client_order_id") == state.get("client_order_id"):
                state["trade"] = event.data

    for event_type in (
        "gateway.login", "gateway.ready", "contract", "fund", "position",
        "position.end", "quote.ready", "tick", "order.snapshot",
        "trade.normalized",
    ):
        bus.subscribe(event_type, on_event)

    base_cfg = V10Config.from_toml(Path("config/esunny.toml"))
    if base_cfg.account != ACCOUNT or base_cfg.front_ip != FRONT or base_cfg.front_port != 6668:
        raise RuntimeError("配置不是已验证的模拟账号或模拟交易前置")
    base_cfg.assert_credentials()
    trade_cfg = dataclasses.replace(base_cfg, live_trading=True)
    quote_cfg = QuoteConfig(
        Path("build/native/esunny_v10_quote_bridge.dll"),
        FRONT,
        6161,
        Path("logs/quote"),
    )

    engine = TradingEngine(
        lambda sink: V10NativeGateway(sink, trade_cfg), event_bus=bus,
    )
    quote_gateway = V10QuoteGateway(bus.publish, quote_cfg)
    storage = OrderStorageService(
        bus,
        SQLiteOrderStore(DATABASE),
        gateway="v10",
        account=ACCOUNT,
        trading_day=datetime.now().astimezone().date().isoformat(),
    )

    bus.start()
    storage.start()
    try:
        engine.connect()
        if not ready.wait(25):
            raise TimeoutError("交易 API 未就绪")
        login = state.get("login")
        if not isinstance(login, dict) or int(login.get("error_code", -1)) != 0:
            raise RuntimeError("交易登录未确认成功")

        engine.query_funds()
        if not fund_ready.wait(10):
            raise TimeoutError("资金查询无回报")
        engine.query_positions()
        if not position_end.wait(10):
            raise TimeoutError("持仓查询未结束")

        position = state.get("position")
        if not isinstance(position, dict):
            raise RuntimeError("没有找到 P2701 多头持仓")
        long_volume = int(position.get("long_yesterday", 0)) + int(
            position.get("long_today", 0),
        )
        if long_volume != 1:
            raise RuntimeError(f"P2701 多头持仓不是预期的 1 手，而是 {long_volume} 手")

        contract = state.get("contract")
        if not isinstance(contract, dict) or int(contract.get("contract_index", 0)) <= 0:
            raise RuntimeError("P2701 合约索引无效")
        contract_index = int(contract["contract_index"])

        quote_gateway.connect()
        if not quote_ready.wait(15):
            raise TimeoutError("行情 API 未就绪")
        quote_gateway.subscribe(QUOTE_CONTRACT)
        if not tick_ready.wait(15):
            raise TimeoutError("没有收到 P2701 行情")
        tick = state["tick"]
        receive_age = time.monotonic() - float(state["tick_seen_at"])
        quote_age = abs(
            (datetime.now() - datetime.fromisoformat(tick.timestamp)).total_seconds(),
        )
        if receive_age > 2 or quote_age > 10:
            raise RuntimeError(
                f"行情不够新：接收延迟 {receive_age:.1f}s，成交时间差 {quote_age:.1f}s",
            )
        price = float(tick.bid_price if tick.bid_price > 0 else tick.last_price)
        if price <= 0 or not tick.lower_limit <= price <= tick.upper_limit:
            raise RuntimeError("买一价无效或超出涨跌停范围")

        client_order_id = engine.close_long(
            QUOTE_CONTRACT,
            price,
            1,
            contract_index=contract_index,
        )
        state["client_order_id"] = client_order_id
        print({
            "status": "submitted",
            "contract": QUOTE_CONTRACT,
            "side": "sell",
            "offset": "close",
            "volume": 1,
            "price": price,
            "quote_time": tick.timestamp,
            "client_order_id": client_order_id,
        }, flush=True)

        if not order_terminal.wait(30):
            print({
                "status": "unknown",
                "message": "30 秒内未收到终态回报；不要重复报单",
                "client_order_id": client_order_id,
            }, flush=True)
            return 2
        order = state["order"]
        print({
            "status": order.status.value,
            "order_id": order.order_id,
            "traded_volume": order.traded_volume,
            "trade": state.get("trade"),
        }, flush=True)
        return 0 if order.status is OrderStatus.FILLED else 3
    finally:
        quote_gateway.close()
        engine.close()
        storage.close()


if __name__ == "__main__":
    raise SystemExit(main())
