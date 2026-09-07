from __future__ import annotations

import ctypes
import json
import os

from ..models import Event
from ..quote_config import QuoteConfig
from ..quote_models import MarketTick
from .base import EventSink
from .quote_base import MarketDataGateway


class V10QuoteGateway(MarketDataGateway):
    """通过 C ABI 桥接层连接官方 DstarQuoteApi，行情接口无需交易账号密码。"""

    _CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p)

    def __init__(self, event_sink: EventSink, config: QuoteConfig) -> None:
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
        self._handle = self._dll.esq_create(self._callback, None)
        if not self._handle:
            raise RuntimeError("创建易盛 V10 行情实例失败")

    def _configure_signatures(self) -> None:
        d = self._dll
        d.esq_create.argtypes = [self._CALLBACK, ctypes.c_void_p]
        d.esq_create.restype = ctypes.c_void_p
        d.esq_destroy.argtypes = [ctypes.c_void_p]
        d.esq_connect.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_ushort, ctypes.c_char_p]
        d.esq_connect.restype = ctypes.c_int
        for name in ("esq_subscribe", "esq_unsubscribe"):
            fn = getattr(d, name)
            fn.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            fn.restype = ctypes.c_int
        d.esq_query_contracts.argtypes = [ctypes.c_void_p]
        d.esq_query_contracts.restype = ctypes.c_int

    @staticmethod
    def _b(value: str) -> bytes:
        return value.encode("gb18030")

    def connect(self) -> None:
        self.config.log_path.mkdir(parents=True, exist_ok=True)
        rc = self._dll.esq_connect(
            self._handle,
            self._b(self.config.front_ip),
            self.config.front_port,
            self._b(str(self.config.log_path.resolve())),
        )
        self._check(rc, "连接")

    def close(self) -> None:
        if self._handle:
            self._dll.esq_destroy(self._handle)
            self._handle = None
        if self._dll_dir_handle:
            self._dll_dir_handle.close()
            self._dll_dir_handle = None

    def subscribe(self, contract: str) -> None:
        self._check(self._dll.esq_subscribe(self._handle, self._b(contract)), "订阅")

    def unsubscribe(self, contract: str) -> None:
        self._check(self._dll.esq_unsubscribe(self._handle, self._b(contract)), "退订")

    def query_contracts(self) -> None:
        self._check(self._dll.esq_query_contracts(self._handle), "合约查询")

    def _on_native_event(self, event_type, payload, _user_data) -> None:
        try:
            kind = event_type.decode("ascii")
            data = json.loads(payload.decode("gb18030")) if payload else {}
            if kind == "tick":
                data = MarketTick(**data)
            self.emit(Event(kind, data))
        except Exception as exc:
            self.emit(Event("quote.error", {"message": f"解析行情回调失败: {exc}"}))

    @staticmethod
    def _check(rc: int, action: str) -> None:
        if rc != 0:
            raise RuntimeError(f"易盛 V10 行情{action}失败，返回码 {rc}")
