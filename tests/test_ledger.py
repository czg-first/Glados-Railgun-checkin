from datetime import datetime
import unittest

from checkin import BEIJING_TZ, today_checkin_points


class LedgerTests(unittest.TestCase):
    now = datetime(2026, 11, 26, 9, 0, tzinfo=BEIJING_TZ)

    def row(self, hour=8, change="2.00000000", business="system:checkin", day=26):
        time = datetime(2026, 11, day, hour, 0, tzinfo=BEIJING_TZ)
        return {"time": int(time.timestamp() * 1000), "change": change, "business": business}

    def points(self, rows, **extra):
        return today_checkin_points({"code": 0, "history": rows, **extra}, self.now)

    def test_exact_checkin_labels_and_fractional_credit(self):
        self.assertEqual(self.points([self.row(change="0.5"), self.row(change="2")]), 2.5)

    def test_yesterday_and_other_business_are_excluded(self):
        self.assertEqual(self.points([self.row(day=25), self.row(business="system:compensation"), self.row(business="system:checkin:refund")]), 0)

    def test_day_is_beijing_day_across_utc_midnight(self):
        self.assertEqual(self.points([self.row(hour=0)]), 2)

    def test_negative_and_zero_are_not_signin_credit(self):
        self.assertEqual(self.points([self.row(change="-2"), self.row(change="0")]), 0)

    def test_unknown_or_rejected_response_remains_unknown(self):
        for data in (None, {}, {"code": -2, "history": []}, {"code": False, "history": []}, {"code": 0}):
            self.assertIsNone(today_checkin_points(data, self.now))

    def test_list_field_and_string_code_are_supported(self):
        self.assertEqual(today_checkin_points({"code": "0", "list": [self.row()]}, self.now), 2)

    def test_malformed_credit_is_not_confirmed(self):
        for change in ("NaN", "inf", True, None):
            self.assertIsNone(self.points([self.row(change=change)]))

    def test_valid_positive_entry_is_enough_even_if_another_is_malformed(self):
        self.assertEqual(self.points([self.row(), self.row(change="NaN")]), 2)
