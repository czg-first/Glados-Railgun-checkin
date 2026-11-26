from types import SimpleNamespace
import unittest

from browser_checkin import cookie_records, is_checkin_response


class BrowserBoundaryTests(unittest.TestCase):
    def response(self, path, method="POST", host="glados.one"):
        return SimpleNamespace(url="https://" + host + path, request=SimpleNamespace(method=method))

    def test_only_final_same_origin_post_is_a_receipt(self):
        self.assertTrue(is_checkin_response(self.response("/api/user/checkin"), "glados.one"))
        self.assertFalse(is_checkin_response(self.response("/api/user/checkin/challenge", "GET"), "glados.one"))
        self.assertFalse(is_checkin_response(self.response("/api/user/checkin", "GET"), "glados.one"))
        self.assertFalse(is_checkin_response(self.response("/api/user/checkin", host="other.example"), "glados.one"))

    def test_cookie_values_and_origin_are_preserved(self):
        records = cookie_records("gld:sess=synthetic==; gld:sess.sig=synthetic-signature", "https://glados.one")
        self.assertEqual(records[0]["value"], "synthetic==")
        self.assertTrue(all(record["url"] == "https://glados.one" and record["secure"] for record in records))
