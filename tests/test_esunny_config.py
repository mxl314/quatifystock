import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quant_framework.adapters.esunny.config import V10Config


class EsunnyConfigTests(unittest.TestCase):
    def test_local_plaintext_password_takes_precedence_without_dpapi(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "esunny.toml").write_text(
                '[esunny]\nbridge_library="bridge.dll"\nfront_ip="123.161.206.213"\n'
                'front_port=6668\naccount="SIM"\napp_id="Demo_TestCollect"\n',
                encoding="utf-8",
            )
            (root / "esunny.local.toml").write_text(
                '[esunny]\npassword="local-only"\n', encoding="utf-8",
            )
            with patch("quant_framework.adapters.esunny.config.load_credentials",
                       side_effect=AssertionError("DPAPI must not be read")):
                config = V10Config.from_toml(root / "esunny.toml")
            self.assertEqual(config.password, "local-only")
            self.assertEqual(config.license_no, "Demo_TestCollect")
            config.assert_credentials()

    def test_non_demo_app_still_requires_license(self):
        config = V10Config(
            bridge_library=Path("bridge.dll"),
            front_ip="127.0.0.1", front_port=6668,
            account="account", password="password", app_id="production-app",
            license_no="",
        )
        with self.assertRaisesRegex(ValueError, "ESUNNY_LICENSE_NO"):
            config.assert_credentials()


if __name__ == "__main__":
    unittest.main()
