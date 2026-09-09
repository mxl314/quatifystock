import unittest

from quant_framework.cli import _parser


class CliTests(unittest.TestCase):
    def test_ctp_gateway_is_available(self):
        args = _parser().parse_args([
            "--gateway", "ctp", "--config", "config/ctp.toml",
            "funds",
        ])
        self.assertEqual(args.gateway, "ctp")
        self.assertEqual(args.action, "funds")


if __name__ == "__main__":
    unittest.main()
