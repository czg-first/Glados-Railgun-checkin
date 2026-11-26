import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import checkin


class ResultReportingTests(unittest.TestCase):
    def report(self, *statuses):
        accounts = checkin.Accounts.parse('[{"cookie":"gld:sess=synthetic-test-only"}]')
        first = next(iter(accounts))
        entries = []
        for index, status in enumerate(statuses, 1):
            entry = checkin.CookieEntry.build(index, first.cookie, origin="glados.one")
            entry.result = checkin.CheckinResult(domain="glados.one", code=status, points=10, today_points=10)
            entries.append(entry)
        return checkin.Report(entries)

    def run_main(self, report):
        env = {"GLADOS_COOKIES": '[{"origin":"glados.one","cookie":"gld:sess=synthetic-test-only"}]'}
        with patch.dict(os.environ, env, clear=True), patch.object(checkin, "init_logger"), patch.object(checkin.PushService, "send"), patch.object(checkin.CheckinRunner, "run", return_value=report):
            try:
                checkin.main()
            except SystemExit as error:
                return error.code
        return 0

    def test_all_completed_pass(self):
        report = self.report(checkin.CheckinStatus.SUCCESS, checkin.CheckinStatus.REPEAT)
        self.assertTrue(report.ok)
        self.assertEqual(self.run_main(report), 0)

    def test_repeat_is_not_a_failure(self):
        self.assertEqual(self.run_main(self.report(checkin.CheckinStatus.REPEAT)), 0)

    def test_partial_failure_marks_action_failed(self):
        report = self.report(checkin.CheckinStatus.SUCCESS, checkin.CheckinStatus.FAILURE)
        self.assertFalse(report.ok)
        self.assertEqual(self.run_main(report), 1)

    def test_all_failed_marks_action_failed(self):
        self.assertEqual(self.run_main(self.report(checkin.CheckinStatus.FAILURE)), 1)

    def test_empty_report_is_not_success(self):
        self.assertFalse(checkin.Report([]).ok)
        self.assertEqual(self.run_main(checkin.Report([])), 1)

    def test_receipt_without_today_credit_does_not_pass(self):
        for observed in (None, 0):
            report = self.report(checkin.CheckinStatus.SUCCESS)
            report.entries[0].result.today_points = observed
            self.assertFalse(report.ok)
            self.assertIn("成功 0 · 失败 1", report.title)
            self.assertIn("入账待核对", report.render())
            self.assertEqual(self.run_main(report), 1)

    def test_missing_and_invalid_config_fail_without_network(self):
        for raw in ("", "invalid", "[]", "{}"):
            with self.subTest(raw=raw), patch.dict(os.environ, {"GLADOS_COOKIES": raw}, clear=True), patch.object(checkin, "init_logger"), patch.object(checkin.PushService, "send"), patch.object(checkin.CheckinRunner, "run") as runner:
                with self.assertRaises(SystemExit) as caught:
                    checkin.main()
                self.assertEqual(caught.exception.code, 1)
                runner.assert_not_called()

    def test_single_account_object_is_supported(self):
        raw = '{"origin":"glados.one","cookie":"gld:sess=synthetic-test-only","user-agent":"test browser"}'
        account = next(iter(checkin.Accounts.parse(raw)))
        self.assertEqual(account.origin, "glados.one")
        self.assertEqual(account.cookie, "gld:sess=synthetic-test-only")
        self.assertEqual(account.user_agent, "test browser")

    def test_single_account_object_still_validates_fields(self):
        for raw in ('{"cookie":"not-a-session"}', '{"cookie":"gld:sess=synthetic-test-only","unexpected":true}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                checkin.Accounts.parse(raw)

    def test_rejection_cannot_be_overridden_by_repeat_flags(self):
        for code in (-2, "-2", 4, 5, 500):
            for flag in ("repeated", "checkedIn"):
                with self.subTest(code=code, flag=flag):
                    result = checkin.parse_checkin({"code": code, flag: True}, "glados.one", lambda *args: None)
                    self.assertIs(result.code, checkin.CheckinStatus.FAILURE)

    def test_malformed_code_cannot_pass(self):
        for code in (None, True, False, 0.0, "unknown"):
            with self.subTest(code=code):
                result = checkin.parse_checkin({"code": code, "repeated": True}, "glados.one", lambda *args: None)
                self.assertIs(result.code, checkin.CheckinStatus.FAILURE)

    def test_string_success_and_repeat_codes(self):
        for code, expected in (("0", checkin.CheckinStatus.SUCCESS), ("1", checkin.CheckinStatus.REPEAT)):
            result = checkin.parse_checkin({"code": code, "points": 10}, "glados.one", lambda *args: None)
            self.assertIs(result.code, expected)

    def test_summary_excludes_credentials_and_names(self):
        report = self.report(checkin.CheckinStatus.SUCCESS)
        report.entries[0].name = "private-account-name"
        report.entries[0].user_agent = "private-user-agent"
        report.entries[0].result.note = "private-raw-response"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "summary.md"
            with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(output)}):
                checkin.write_actions_summary(report)
            text = output.read_text(encoding="utf-8")
            self.assertIn("glados.one", text)
            self.assertIn("10", text)
            for secret in (report.entries[0].cookie, "private-account-name", "private-user-agent", "private-raw-response"):
                self.assertNotIn(secret, text)

    def test_low_points_are_flagged_for_confirmation(self):
        report = self.report(checkin.CheckinStatus.SUCCESS)
        report.entries[0].result.points = 1
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "summary.md"
            with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(output)}):
                checkin.write_actions_summary(report)
            self.assertIn("可能受到自动签到限制", output.read_text(encoding="utf-8"))

    def test_summary_file_failure_does_not_change_result(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": directory}):
            checkin.write_actions_summary(self.report(checkin.CheckinStatus.SUCCESS))


if __name__ == "__main__":
    unittest.main()
