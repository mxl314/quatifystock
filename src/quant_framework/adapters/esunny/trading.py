from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path

from .config import V10Config
from ...core.models import Event, OrderRequest
from ...core.interfaces import EventSink, TradingGateway


class V10NativeGateway(TradingGateway):
    """通过本项目 C ABI 桥接库访问官方易盛 V10 C++ API。"""

    _CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p)

    def __init__(self, event_sink: EventSink, config: V10Config) -> None:
        super().__init__(event_sink)
        self.config = config
        library_path = config.bridge_library.resolve()
        self._dll_dir_handle = (
            os.add_dll_directory(str(library_path.parent))
            if hasattr(os, "add_dll_directory")
            else None
        )
        self._dll = ctypes.CDLL(str(library_path))
        self._configure_signatures()
        self._callback = self._CALLBACK(self._on_native_event)
        self._handle = self._dll.es_create(self._callback, None)
        if not self._handle:
            raise RuntimeError("创建易盛 V10 桥接实例失败")

    def _configure_signatures(self) -> None:
        d = self._dll
        d.es_create.argtypes = [self._CALLBACK, ctypes.c_void_p]
        d.es_create.restype = ctypes.c_void_p
        d.es_destroy.argtypes = [ctypes.c_void_p]
        d.es_connect.argtypes = [ctypes.c_void_p] + [ctypes.c_char_p] * 6 + [ctypes.c_ushort]
        d.es_connect.restype = ctypes.c_int
        d.es_insert_order.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_uint,
            ctypes.c_char,
            ctypes.c_char,
            ctypes.c_char,
            ctypes.c_char,
            ctypes.c_char,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.c_double,
            ctypes.c_uint,
            ctypes.c_longlong,
            ctypes.c_uint,
        ]
        d.es_insert_order.restype = ctypes.c_int
        d.es_cancel_order.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulonglong,
            ctypes.c_char_p,
            ctypes.c_uint,
            ctypes.c_longlong,
            ctypes.c_uint,
        ]
        d.es_cancel_order.restype = ctypes.c_int
        for name in ("es_query_funds", "es_query_positions"):
            fn = getattr(d, name)
            fn.argtypes = [ctypes.c_void_p]
            fn.restype = ctypes.c_int

    @staticmethod
    def _b(value: str | Path) -> bytes:
        return str(value).encode("gb18030")

    def connect(self) -> None:
        self.config.assert_credentials()
        self.config.log_path.mkdir(parents=True, exist_ok=True)
        rc = self._dll.es_connect(
            self._handle,
            self._b(self.config.front_ip),
            self._b(self.config.account),
            self._b(self.config.password),
            self._b(self.config.app_id),
            self._b(self.config.license_no),
            self._b(self.config.log_path.resolve()),
            self.config.front_port,
        )
        self._check(rc, "连接")

    def close(self) -> None:
        if self._handle:
            self._dll.es_destroy(self._handle)
            self._handle = None
        if self._dll_dir_handle:
            self._dll_dir_handle.close()
            self._dll_dir_handle = None

    def _assert_live(self) -> None:
        if not self.config.live_trading or os.getenv("ESUNNY_LIVE_CONFIRM") != "I_UNDERSTAND":
            raise PermissionError(
                "真实发单被锁定：需要 live_trading=true 与 "
                "ESUNNY_LIVE_CONFIRM=I_UNDERSTAND"
            )

    def send_order(self, request_id: int, order: OrderRequest) -> None:
        self._assert_live()
        reference = order.reference if order.reference is not None else request_id
        rc = self._dll.es_insert_order(
            self._handle,
            self._b(order.contract),
            order.contract_index,
            order.side.value.encode(),
            order.offset.value.encode(),
            order.hedge.value.encode(),
            order.order_type.value.encode(),
            order.time_in_force.value.encode(),
            order.volume,
            order.min_volume,
            order.price,
            request_id,
            reference,
            order.seat_index,
        )
        self._check(rc, "报单")

    def cancel_order(self, request_id: int, order_id: int, system_no: str = "") -> None:
        self._assert_live()
        rc = self._dll.es_cancel_order(
            self._handle,
            order_id,
            self._b(system_no),
            request_id,
            request_id,
            0,
        )
        self._check(rc, "撤单")

    def query_funds(self) -> None:
        self._check(self._dll.es_query_funds(self._handle), "资金查询")

    def query_positions(self) -> None:
        self._check(self._dll.es_query_positions(self._handle), "持仓查询")

    def _on_native_event(self, event_type, payload, _user_data) -> None:
        try:
            kind = event_type.decode("ascii")
            data = json.loads(payload.decode("gb18030")) if payload else None
            self.emit(Event(kind, data))
        except Exception as exc:
            self.emit(Event("gateway.error", {"message": f"解析原生回调失败: {exc}"}))

    @staticmethod
    def _check(rc: int, action: str) -> None:
        if rc != 0:
            raise RuntimeError(f"易盛 V10 {action}失败，返回码 {rc}")
