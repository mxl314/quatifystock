from __future__ import annotations

import re

_FUTURE = re.compile(r"^([A-Za-z]+)(\d+)$")
_EXCHANGES = {"CFFEX", "CZCE", "DCE", "GFEX", "INE", "SHFE"}


def to_canonical(instrument: str, exchange: str) -> str:
    instrument = instrument.strip()
    exchange = exchange.strip().upper()
    match = _FUTURE.fullmatch(instrument)
    if exchange in _EXCHANGES and match:
        product, delivery = match.groups()
        return f"{exchange}|F|{product.upper()}|{delivery}"
    return f"{exchange or 'CTP'}|CTP|{instrument}"


def from_canonical(contract: str) -> tuple[str, str]:
    parts = contract.strip().split("|")
    if len(parts) == 4 and parts[1] == "F":
        exchange, _, product, delivery = parts
        if exchange.upper() not in _EXCHANGES:
            raise ValueError(f"不支持的 CTP 交易所: {exchange}")
        product = product.upper() if exchange.upper() in {"CFFEX", "CZCE"} else product.lower()
        return product + delivery, exchange.upper()
    if len(parts) == 3 and parts[1] == "CTP":
        return parts[2], "" if parts[0] == "CTP" else parts[0].upper()
    raise ValueError("CTP 合约格式应为 EXCHANGE|F|PRODUCT|DELIVERY，例如 DCE|F|P|2701")
