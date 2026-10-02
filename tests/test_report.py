import json
import unittest

from app.models.execution_result import (
    ExecutionErrorKind,
    ExecutionOutcome,
    TestExecutionResult,
)
from app.models.test_case import TestCase
from app.report.summary import build_execution_report


class ExecutionReportTests(unittest.TestCase):
    def test_summarizes_outcomes_and_groups_without_response_secrets(self):
        results = [
            self._result("valid", "positive", ExecutionOutcome.PASSED, [200], 200),
            self._result("invalid", "negative", ExecutionOutcome.FAILED, [422], 400),
            self._result("timeout", "positive", ExecutionOutcome.ERROR, [200], None,
                         error_kind=ExecutionErrorKind.TIMEOUT, error="request timed out"),
            self._result("unknown expectation", "positive", ExecutionOutcome.UNVERIFIED, None, 200),
            self._result("not selected", "negative", ExecutionOutcome.SKIPPED, None, None),
        ]

        report = build_execution_report(results)

        self.assertEqual(report["summary"]["total_tests"], 5)
        self.assertEqual(report["summary"]["executed_tests"], 4)
        self.assertEqual(report["summary"]["assertions_evaluated"], 2)
        self.assertEqual(report["summary"]["pass_rate"], 0.5)
        self.assertEqual(report["summary"]["counts"]["unverified"], 1)
        self.assertEqual(report["summary"]["counts"]["skipped"], 1)
        self.assertEqual(len(report["by_endpoint"]), 1)
        self.assertEqual(report["by_endpoint"][0]["counts"]["failed"], 1)
        self.assertEqual(report["by_test_type"]["negative"]["skipped"], 1)

        serialized = json.dumps(report)
        self.assertNotIn("secret response body", serialized)
        self.assertNotIn("set-cookie", serialized.lower())
        self.assertNotIn("Authorization", serialized)

    def test_empty_and_unverified_only_reports_have_no_pass_rate(self):
        self.assertIsNone(build_execution_report([])["summary"]["pass_rate"])
        result = self._result("unverified", "positive", ExecutionOutcome.UNVERIFIED, None, 200)
        self.assertIsNone(build_execution_report([result])["summary"]["pass_rate"])

    @staticmethod
    def _result(name, test_type, outcome, expected, actual, **kwargs):
        return TestExecutionResult(
            test_case=TestCase(
                name=name,
                method="GET",
                path="/health",
                type=test_type,
                expected_status=expected,
            ),
            outcome=outcome,
            actual_status=actual,
            response_headers={"set-cookie": "session=secret", "Authorization": "secret"},
            response_body="secret response body",
            duration_ms=5.5,
            **kwargs,
        )


if __name__ == "__main__":
    unittest.main()
