import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.analysis.failure_analyzer import FailureAnalysis
from app.api.test_runs import run_tests
from app.models.execution_result import ExecutionOutcome, TestExecutionResult
from app.models.test_case import TestCase
from app.models.test_run import TestRunRequest


class TestRunApiTests(unittest.TestCase):
    def test_executes_explicit_allowlisted_batch_and_returns_safe_report(self):
        request = self._request()
        with patch("app.api.test_runs.execute_test_case", side_effect=self._execute) as execute:
            response = run_tests(request)

        self.assertEqual(execute.call_count, 2)
        self.assertEqual(response["report"]["summary"]["counts"]["passed"], 1)
        self.assertEqual(response["report"]["summary"]["counts"]["failed"], 1)
        self.assertEqual(response["report"]["summary"]["pass_rate"], 0.5)
        self.assertIsNone(response["analysis"])
        self.assertNotIn("response_body", str(response))
        self.assertNotIn("secret body", str(response))

    def test_rejects_unallowlisted_target_and_mutating_tests_before_execution(self):
        with patch("app.api.test_runs.execute_test_case") as execute:
            with self.assertRaises(HTTPException) as raised:
                run_tests(self._request(base_url="https://other.example"))
            self.assertEqual(raised.exception.status_code, 400)
            execute.assert_not_called()

            with self.assertRaises(HTTPException) as raised:
                run_tests(self._request(test_cases=[self._case(method="DELETE")]))
            self.assertIn("allow_mutating_methods", raised.exception.detail)
            execute.assert_not_called()

    def test_opt_in_analysis_is_called_only_for_failed_results(self):
        request = self._request(analyze_failures=True)
        analysis = FailureAnalysis(
            summary="Observed failure.",
            observed_facts=["One expected status did not match."],
            hypotheses=[],
            recommendations=[],
        )
        with (
            patch("app.api.test_runs.execute_test_case", side_effect=self._execute),
            patch("app.api.test_runs.OpenAIResponsesProvider.from_environment", return_value=object()),
            patch("app.api.test_runs.analyze_failures", return_value=analysis) as analyze,
        ):
            response = run_tests(request)

        analyze.assert_called_once()
        self.assertEqual(response["analysis"]["summary"], "Observed failure.")
        self.assertIsNone(response["analysis_error"])

    def test_analysis_configuration_is_checked_before_any_request(self):
        with (
            patch("app.api.test_runs.execute_test_case") as execute,
            patch("app.api.test_runs.OpenAIResponsesProvider.from_environment", side_effect=ValueError("missing config")),
        ):
            with self.assertRaises(HTTPException) as raised:
                run_tests(self._request(analyze_failures=True))

        self.assertEqual(raised.exception.status_code, 503)
        execute.assert_not_called()

    @staticmethod
    def _case(name="health", method="GET"):
        return TestCase(
            name=name,
            method=method,
            path="/health",
            type="positive",
            expected_status=[200],
        )

    @classmethod
    def _request(cls, **overrides):
        values = {
            "test_cases": [cls._case(), cls._case(name="also health")],
            "base_url": "https://api.example.com",
            "allowed_hosts": {"api.example.com"},
        }
        values.update(overrides)
        return TestRunRequest(**values)

    @staticmethod
    def _execute(test_case, base_url, **kwargs):
        passed = test_case.name == "health"
        return TestExecutionResult(
            test_case=test_case,
            outcome=ExecutionOutcome.PASSED if passed else ExecutionOutcome.FAILED,
            actual_status=200 if passed else 500,
            response_body="secret body",
            duration_ms=1,
        )


if __name__ == "__main__":
    unittest.main()
