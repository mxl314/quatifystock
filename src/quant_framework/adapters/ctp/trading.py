from __future__ import annotations

import ctypes
import json
import os
from dataclasses import dataclass

from ...core.interfaces import EventSink, TradingGateway
from ...core.models import Event, OrderRequest
from .config import CtpConfig
from .mapper import from_canonical, to_canonical


@dataclass(slots=True)
class _OrderRoute:
    instrument: str
    exchange: str
    order_ref: str
    front_id: int = 0
    session_id: int = 0
    system_no: str = ""


class CtpTradingGateway(TradingGateway):
    _CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p)

    def __init__(self, event_sink: EventSink, config: CtpConfig) -> None:
        super().__init__(event_sink)
        self.config = config
        self._routes: dict[int, _OrderRoute] = {}
        library = config.td_bridge_library.resolve()
        self._dll_dir_handle = os.add_dll_directory(str(library.parent)) if hasattr(os, "add_dll_directory") else None
        self._dll = ctypes.CDLL(str(library))
        self._configure_signatures()
        self._callback = self._CALLBACK(self._on_native_event)
        self._handle = self._dll.ctp_td_create(self._callback, None)
        if not self._handle:
            raise RuntimeError("创建 CTP 交易桥接实例失败")

    def _configure_signatures(self) -> None:
        d = self._dll
        d.ctp_td_create.argtypes = [self._CALLBACK, ctypes.c_void_p]; d.ctp_td_create.restype = ctypes.c_void_p
        d.ctp_td_destroy.argtypes = [ctypes.c_void_p]
        d.ctp_td_connect.argtypes = [ctypes.c_void_p] + [ctypes.c_char_p] * 7; d.ctp_td_connect.restype = ctypes.c_int
        d.ctp_td_insert_order.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p] + [ctypes.c_char] * 5 + [ctypes.c_int, ctypes.c_int, ctypes.c_double, ctypes.c_int, ctypes.c_int]
        d.ctp_td_insert_order.restype = ctypes.c_int
        d.ctp_td_cancel_order.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
        d.ctp_td_cancel_order.restype = ctypes.c_int
        for name in ("ctp_td_query_funds", "ctp_td_query_positions", "ctp_td_query_contracts"):
            fn = getattr(d, name); fn.argtypes = [ctypes.c_void_p]; fn.restype = ctypes.c_int

    @staticmethod
    def _b(value: object) -> bytes:
        return str(value).encode("gb18030")

    def connect(self) -> None:
        self.config.assert_credentials()
        flow = self.config.flow_path / "td"; flow.mkdir(parents=True, exist_ok=True)
        self._check(self._dll.ctp_td_connect(
            self._handle, self._b(self.config.td_front), self._b(self.config.broker_id),
            self._b(self.config.user_id), self._b(self.config.password), self._b(self.config.app_id),
            self._b(self.config.auth_code), self._b(str(flow.resolve()) + os.sep),
        ), "连接交易")

    def close(self) -> None:
        if self._handle:
            self._dll.ctp_td_destroy(self._handle); self._handle = None
        if self._dll_dir_handle:
            self._dll_dir_handle.close(); self._dll_dir_handle = None

    def _assert_live(self) -> None:
        if not self.config.live_trading or os.getenv("CTP_LIVE_CONFIRM") != "I_UNDERSTAND":
            raise PermissionError("CTP 发单被锁定：需要 live_trading=true 且 CTP_LIVE_CONFIRM=I_UNDERSTAND")

    def send_order(self, request_id: int, order: OrderRequest) -> None:
        self._assert_live()
        instrument, exchange = from_canonical(order.contract)
        order_ref = order.reference if order.reference is not None else request_id
        self._routes[order_ref] = _OrderRoute(instrument, exchange, str(order_ref))
        self._check(self._dll.ctp_td_insert_order(
            self._handle, self._b(instrument), self._b(exchange), order.side.value.encode(),
            order.offset.value.encode(), order.hedge.value.encode(), order.order_type.value.encode(),
            order.time_in_force.value.encode(), order.volume, order.min_volume, order.price,
            request_id, order_ref,
        ), "报单")

    def cancel_order(self, request_id: int, order_id: int, system_no: str = "") -> None:
        self._assert_live()
        route = self._routes.get(order_id)
        if not route:
            raise KeyError(f"找不到 CTP 委托路由信息: {order_id}")
        self._check(self._dll.ctp_td_cancel_order(
            self._handle, self._b(route.instrument), self._b(route.exchange), self._b(route.order_ref),
            route.front_id, route.session_id, self._b(system_no or route.system_no), request_id,
        ), "撤单")

    def query_funds(self) -> None:
        self._check(self._dll.ctp_td_query_funds(self._handle), "资金查询")

    def query_positions(self) -> None:
        self._check(self._dll.ctp_td_query_positions(self._handle), "持仓查询")

    def query_contracts(self) -> None:
        self._check(self._dll.ctp_td_query_contracts(self._handle), "合约查询")

    def _on_native_event(self, event_type, payload, _user_data) -> None:
        try:
            kind = event_type.decode("ascii")
            data = json.loads(payload.decode("gb18030")) if payload else {}
            if isinstance(data, dict) and "instrument" in data:
                data["contract"] = to_canonical(data["instrument"], data.get("exchange", ""))
            if kind == "order" and data.get("order_id"):
                oid = int(data["order_id"])
                route = self._routes.get(oid) or _OrderRoute(data.get("instrument", ""), data.get("exchange", ""), data.get("order_ref", str(oid)))
                route.front_id = int(data.get("front_id", route.front_id)); route.session_id = int(data.get("session_id", route.session_id)); route.system_no = data.get("system_no", route.system_no)
                self._routes[oid] = route
            self.emit(Event(kind, data))
        except Exception as exc:
            self.emit(Event("gateway.error", {"gateway": "ctp.td", "message": f"解析 CTP 交易回调失败: {exc}"}))

    @staticmethod
    def _check(rc: int, action: str) -> None:
        if rc != 0:
            raise RuntimeError(f"CTP {action}失败，返回码 {rc}")
