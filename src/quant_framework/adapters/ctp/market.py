from __future__ import annotations

import ctypes
import json
import os

from ...core.interfaces import EventSink, MarketDataGateway
from ...core.models import Event, MarketTick
from .config import CtpConfig
from .mapper import from_canonical, to_canonical


class CtpMarketGateway(MarketDataGateway):
    _CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p)

    def __init__(self, event_sink: EventSink, config: CtpConfig) -> None:
        super().__init__(event_sink)
        self.config = config
        # CTP depth-market-data callbacks may omit ExchangeID.  Keep the
        # canonical contract supplied by the caller so upper layers never
        # depend on gateway-specific or incomplete identifiers.
        self._subscriptions: dict[str, str] = {}
        library = config.md_bridge_library.resolve()
        self._dll_dir_handle = os.add_dll_directory(str(library.parent)) if hasattr(os, "add_dll_directory") else None
        self._dll = ctypes.CDLL(str(library))
        self._configure_signatures()
        self._callback = self._CALLBACK(self._on_native_event)
        self._handle = self._dll.ctp_md_create(self._callback, None)
        if not self._handle:
            raise RuntimeError("创建 CTP 行情桥接实例失败")

    def _configure_signatures(self) -> None:
        d = self._dll
        d.ctp_md_create.argtypes = [self._CALLBACK, ctypes.c_void_p]
        d.ctp_md_create.restype = ctypes.c_void_p
        d.ctp_md_destroy.argtypes = [ctypes.c_void_p]
        d.ctp_md_connect.argtypes = [ctypes.c_void_p] + [ctypes.c_char_p] * 5
        d.ctp_md_connect.restype = ctypes.c_int
        for name in ("ctp_md_subscribe", "ctp_md_unsubscribe"):
            fn = getattr(d, name); fn.argtypes = [ctypes.c_void_p, ctypes.c_char_p]; fn.restype = ctypes.c_int

    @staticmethod
    def _b(value: object) -> bytes:
        return str(value).encode("gb18030")

    def connect(self) -> None:
        self.config.assert_credentials()
        flow = self.config.flow_path / "md"
        flow.mkdir(parents=True, exist_ok=True)
        self._check(self._dll.ctp_md_connect(
            self._handle, self._b(self.config.md_front), self._b(self.config.broker_id),
            self._b(self.config.user_id), self._b(self.config.password), self._b(str(flow.resolve()) + os.sep),
        ), "连接行情")

    def close(self) -> None:
        if self._handle:
            self._dll.ctp_md_destroy(self._handle); self._handle = None
        if self._dll_dir_handle:
            self._dll_dir_handle.close(); self._dll_dir_handle = None

    def subscribe(self, contract: str) -> None:
        instrument, _ = from_canonical(contract)
        self._check(self._dll.ctp_md_subscribe(self._handle, self._b(instrument)), "订阅")
        self._subscriptions[instrument.lower()] = contract

    def unsubscribe(self, contract: str) -> None:
        instrument, _ = from_canonical(contract)
        self._check(self._dll.ctp_md_unsubscribe(self._handle, self._b(instrument)), "退订")
        self._subscriptions.pop(instrument.lower(), None)

    def query_contracts(self) -> None:
        raise NotImplementedError("CTP 合约查询由交易接口提供")

    def _on_native_event(self, event_type, payload, _user_data) -> None:
        try:
            kind = event_type.decode("ascii")
            data = json.loads(payload.decode("gb18030")) if payload else {}
            if kind == "gateway.ready":
                kind = "quote.ready"
            elif kind == "gateway.error":
                kind = "quote.error"
            if kind == "tick":
                instrument = data.pop("instrument")
                exchange = data.pop("exchange")
                data["contract"] = self._subscriptions.get(
                    instrument.lower(),
                    to_canonical(instrument, exchange),
                )
                data = MarketTick(**data)
            self.emit(Event(kind, data))
        except Exception as exc:
            self.emit(Event("gateway.error", {"gateway": "ctp.md", "message": f"解析 CTP 行情回调失败: {exc}"}))

    @staticmethod
    def _check(rc: int, action: str) -> None:
        if rc != 0:
            raise RuntimeError(f"CTP {action}失败，返回码 {rc}")
