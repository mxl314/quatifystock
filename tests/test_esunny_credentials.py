import unittest
from unittest.mock import patch

from quant_framework.adapters.esunny.credentials import clear_license, update_password


class CredentialMutationTests(unittest.TestCase):
    def test_password_update_keeps_deleted_license_absent(self):
        data = {"account": "Q1062383955", "password": "old"}
        with patch("quant_framework.adapters.esunny.credentials.load_credentials", return_value=data), \
             patch("quant_framework.adapters.esunny.credentials._save_payload") as save:
            update_password("Q1062383955", "new")
        self.assertEqual(save.call_args.args[0],
                         {"account": "Q1062383955", "password": "new"})

    def test_clear_license_preserves_account_and_password(self):
        data = {"account": "Q1062383955", "password": "kept", "license_no": "removed"}
        with patch("quant_framework.adapters.esunny.credentials.load_credentials", return_value=data), \
             patch("quant_framework.adapters.esunny.credentials._save_payload") as save:
            self.assertTrue(clear_license())
        self.assertEqual(save.call_args.args[0],
                         {"account": "Q1062383955", "password": "kept"})


if __name__ == "__main__":
    unittest.main()
