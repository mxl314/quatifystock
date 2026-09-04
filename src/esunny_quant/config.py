from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class V10Config:
    bridge_library: Path
    front_ip: str
    front_port: int
    account: str
    password: str
    app_id: str
    license_no: str
    log_path: Path = Path("logs")
    live_trading: bool = False

    @classmethod
    def from_toml(cls, path: str | Path) -> "V10Config":
        raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))["esunny"]
        env = os.environ
        return cls(
            bridge_library=Path(raw["bridge_library"]),
            front_ip=raw["front_ip"], front_port=int(raw["front_port"]),
            account=env.get("ESUNNY_ACCOUNT", raw.get("account", "")),
            password=env.get("ESUNNY_PASSWORD", ""),
            app_id=env.get("ESUNNY_APP_ID", raw.get("app_id", "")),
            license_no=env.get("ESUNNY_LICENSE_NO", ""),
            log_path=Path(raw.get("log_path", "logs")),
            live_trading=bool(raw.get("live_trading", False)),
        )

    def assert_credentials(self) -> None:
        missing = [name for name, value in {
            "ESUNNY_ACCOUNT": self.account, "ESUNNY_PASSWORD": self.password,
            "ESUNNY_APP_ID": self.app_id, "ESUNNY_LICENSE_NO": self.license_no,
        }.items() if not value]
        if missing:
            raise ValueError("缺少环境变量: " + ", ".join(missing))

