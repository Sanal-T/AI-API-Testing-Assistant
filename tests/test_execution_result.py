import unittest

from app.models.execution_result import ExecutionOutcome, TestExecutionResult
from app.models.test_case import TestCase


class TestExecutionResultModelTests(unittest.TestCase):
    def test_serializes_test_definition_separately_from_observed_result(self):
        test_case = TestCase(
            name="fetch user",
            method="GET",
            path="/users/{user_id}",
            type="positive",
            path_params={"user_id": 7},
            expected_status=[200],
        )
        result = TestExecutionResult(
            test_case=test_case,
            outcome=ExecutionOutcome.PASSED,
            actual_status=200,
            response_headers={"content-type": "application/json"},
            response_body='{"id":7}',
            duration_ms=12.5,
        )

        data = result.model_dump(mode="json")

        self.assertEqual(data["test_case"]["expected_status"], [200])
        self.assertEqual(data["actual_status"], 200)
        self.assertEqual(data["outcome"], "passed")
        self.assertEqual(data["duration_ms"], 12.5)

    def test_represents_skipped_tests_without_claiming_a_request_was_sent(self):
        result = TestExecutionResult(
            test_case=TestCase(
                name="not selected",
                method="GET",
                path="/users",
                type="positive",
            ),
            outcome=ExecutionOutcome.SKIPPED,
            duration_ms=0,
        )

        self.assertIsNone(result.actual_status)
        self.assertEqual(result.outcome, ExecutionOutcome.SKIPPED)


if __name__ == "__main__":
    unittest.main()
