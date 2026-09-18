import unittest
import json
import tempfile
from unittest.mock import patch
from pathlib import Path

from quant_framework.adapters.ctp import CtpAdapter, CtpConfig
from quant_framework.adapters.ctp.market import CtpMarketGateway
from quant_framework.adapters.ctp.mapper import from_canonical, to_canonical


class CtpMapperTests(unittest.TestCase):
    def test_dce_round_trip(self):
        self.assertEqual(from_canonical("DCE|F|P|2701"), ("p2701", "DCE"))
        self.assertEqual(to_canonical("p2701", "DCE"), "DCE|F|P|2701")

    def test_cffex_keeps_uppercase(self):
        self.assertEqual(from_canonical("CFFEX|F|IF|2612"), ("IF2612", "CFFEX"))

    def test_capabilities(self):
        self.assertTrue(CtpAdapter.capabilities.market_data)
        self.assertTrue(CtpAdapter.capabilities.trading)
        self.assertFalse(CtpAdapter.capabilities.historical_data)

    def test_market_tick_uses_subscribed_canonical_contract_when_exchange_missing(self):
        events = []
        gateway = CtpMarketGateway.__new__(CtpMarketGateway)
        gateway.emit = events.append
        gateway._subscriptions = {"ag2611": "SHFE|F|AG|2611"}
        payload = json.dumps({
            "instrument": "ag2611", "exchange": "",
            "timestamp": "2026-09-18 00:00:00.000",
            "last_price": 16000,
        }).encode("gb18030")

        gateway._on_native_event(b"tick", payload, None)

        self.assertEqual(events[0].data.contract, "SHFE|F|AG|2611")


class CtpLibraryTests(unittest.TestCase):
    def test_compiled_libraries_exist(self):
        root = Path(__file__).resolve().parents[1]
        self.assertTrue((root / "build/native/ctp_md_bridge.dll").is_file())
        self.assertTrue((root / "build/native/ctp_td_bridge.dll").is_file())


class CtpConfigTests(unittest.TestCase):
    def test_local_password_is_loaded_without_putting_it_in_main_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            main = root / "ctp.toml"
            main.write_text("""
[ctp]
md_bridge_library = "md.dll"
td_bridge_library = "td.dll"
md_front = "tcp://md"
td_front = "tcp://td"
user_id = "demo-user"
""", encoding="utf-8")
            (root / "ctp.local.toml").write_text("""
[ctp]
password = "local-secret"
""", encoding="utf-8")
            with patch.dict("os.environ", {}, clear=True):
                config = CtpConfig.from_toml(main)
            self.assertEqual(config.user_id, "demo-user")
            self.assertEqual(config.password, "local-secret")

    def test_environment_overrides_local_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            main = root / "ctp.toml"
            main.write_text("""
[ctp]
md_bridge_library = "md.dll"
td_bridge_library = "td.dll"
md_front = "tcp://md"
td_front = "tcp://td"
user_id = "main-user"
""", encoding="utf-8")
            (root / "ctp.local.toml").write_text("""
[ctp]
password = "local-secret"
""", encoding="utf-8")
            with patch.dict(
                "os.environ",
                {"CTP_USER_ID": "env-user", "CTP_PASSWORD": "env-secret"},
                clear=False,
            ):
                config = CtpConfig.from_toml(main)
            self.assertEqual(config.user_id, "env-user")
            self.assertEqual(config.password, "env-secret")


if __name__ == "__main__":
    unittest.main()
