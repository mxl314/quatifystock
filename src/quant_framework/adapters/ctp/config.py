from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CtpConfig:
    md_bridge_library: Path
    td_bridge_library: Path
    md_front: str
    td_front: str
    broker_id: str = "9999"
    user_id: str = ""
    password: str = ""
    app_id: str = "simnow_client_test"
    auth_code: str = "0000000000000000"
    flow_path: Path = Path("runtime/ctp")
    live_trading: bool = False

    @classmethod
    def from_toml(cls, path: str | Path) -> "CtpConfig":
        path = Path(path)
        raw = tomllib.loads(path.read_text(encoding="utf-8"))["ctp"]
        local_path = path.with_name(path.stem + ".local.toml")
        local_raw = (
            tomllib.loads(local_path.read_text(encoding="utf-8"))["ctp"]
            if local_path.is_file() else {}
        )
        env = os.environ
        return cls(
            md_bridge_library=Path(raw["md_bridge_library"]),
            td_bridge_library=Path(raw["td_bridge_library"]),
            md_front=str(raw["md_front"]),
            td_front=str(raw["td_front"]),
            broker_id=env.get(
                "CTP_BROKER_ID",
                str(local_raw.get("broker_id", raw.get("broker_id", "9999"))),
            ),
            user_id=env.get(
                "CTP_USER_ID",
                str(local_raw.get("user_id", raw.get("user_id", ""))),
            ),
            password=env.get(
                "CTP_PASSWORD",
                str(local_raw.get("password", raw.get("password", ""))),
            ),
            app_id=env.get("CTP_APP_ID", str(raw.get("app_id", "simnow_client_test"))),
            auth_code=env.get("CTP_AUTH_CODE", str(raw.get("auth_code", "0000000000000000"))),
            flow_path=Path(raw.get("flow_path", "runtime/ctp")),
            live_trading=bool(raw.get("live_trading", False)),
        )

    def assert_credentials(self) -> None:
        missing = [name for name, value in {
            "CTP_USER_ID": self.user_id,
            "CTP_PASSWORD": self.password,
        }.items() if not value]
        if missing:
            raise ValueError("缺少环境变量: " + ", ".join(missing))
