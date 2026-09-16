from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .credentials import load_credentials


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
        path = Path(path)
        raw = tomllib.loads(path.read_text(encoding="utf-8"))["esunny"]
        local_path = path.with_name(path.stem + ".local.toml")
        local_raw = (tomllib.loads(local_path.read_text(encoding="utf-8"))["esunny"]
                     if local_path.is_file() else {})
        env = os.environ
        encrypted = (load_credentials() if os.name == "nt" and not (
            env.get("ESUNNY_PASSWORD") or local_raw.get("password") or raw.get("password")) else {})
        account = env.get("ESUNNY_ACCOUNT", local_raw.get("account", raw.get("account", "")))
        if encrypted and encrypted.get("account") != account:
            raise ValueError("本机凭据账号与易盛配置账号不一致")
        return cls(
            bridge_library=Path(raw["bridge_library"]),
            front_ip=raw["front_ip"], front_port=int(raw["front_port"]),
            account=account,
            password=env.get("ESUNNY_PASSWORD", local_raw.get("password", raw.get("password", encrypted.get("password", "")))),
            app_id=env.get("ESUNNY_APP_ID", local_raw.get("app_id", raw.get("app_id", ""))),
            license_no=env.get("ESUNNY_LICENSE_NO", local_raw.get("license_no", raw.get("license_no", encrypted.get("license_no", "")))),
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
