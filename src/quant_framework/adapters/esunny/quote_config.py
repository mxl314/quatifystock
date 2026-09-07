from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class QuoteConfig:
    bridge_library: Path
    front_ip: str = "61.163.243.173"
    front_port: int = 6161
    log_path: Path = Path("logs/quote")

    @classmethod
    def from_toml(cls, path: str | Path) -> "QuoteConfig":
        raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))["quote"]
        return cls(
            bridge_library=Path(raw["bridge_library"]),
            front_ip=str(raw.get("front_ip", "61.163.243.173")),
            front_port=int(raw.get("front_port", 6161)),
            log_path=Path(raw.get("log_path", "logs/quote")),
        )

