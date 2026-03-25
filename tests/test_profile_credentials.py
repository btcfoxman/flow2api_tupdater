import unittest

from token_updater import api


class ProfileCredentialHelperTests(unittest.TestCase):
    def test_parse_account_import_content_supports_two_and_three_columns(self):
        items = api._parse_account_import_content(
            "主账号,alpha@example.com,pass-1\nbeta@example.com,pass-2\n"
        )

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["name"], "主账号")
        self.assertEqual(items[0]["login_account"], "alpha@example.com")
        self.assertEqual(items[0]["login_password"], "pass-1")
        self.assertEqual(items[1]["name"], "beta@example.com")
        self.assertEqual(items[1]["login_account"], "beta@example.com")
        self.assertEqual(items[1]["login_password"], "pass-2")

    def test_parse_account_import_content_reports_line_number(self):
        with self.assertRaises(api.HTTPException) as ctx:
            api._parse_account_import_content("only-one-column")

        self.assertIn("第 1 行", str(ctx.exception.detail))

    def test_resolve_login_credentials_requires_complete_pair(self):
        with self.assertRaises(api.HTTPException):
            api._resolve_login_credentials("", "", "alpha@example.com", None)

    def test_serialize_profile_masks_password_by_default(self):
        profile = {
            "id": 7,
            "name": "alpha",
            "login_account": "alpha@example.com",
            "login_password": "secret-pass-123",
            "flow2api_url": "",
            "connection_token_override": "",
            "proxy_url": "",
        }

        data = api._serialize_profile(profile, active_id=None)
        self.assertTrue(data["has_login_credentials"])
        self.assertEqual(data["login_account"], "alpha@example.com")
        self.assertNotIn("login_password", data)
        self.assertEqual(data["login_password_preview"], "secr...-123")

        detail = api._serialize_profile(profile, active_id=7, include_secret=True)
        self.assertEqual(detail["login_password"], "secret-pass-123")
        self.assertTrue(detail["is_browser_active"])


if __name__ == "__main__":
    unittest.main()
