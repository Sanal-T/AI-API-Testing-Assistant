import json
import unittest
from unittest.mock import patch

from app.analysis.failure_analyzer import (
    FailureAnalysis,
    OpenAIResponsesProvider,
    analyze_failures,
)
from app.models.execution_result import ExecutionOutcome, TestExecutionResult
from app.models.test_case import TestCase


class _FakeProvider:
    def __init__(self):
        self.evidence = None

    def analyze(self, evidence):
        self.evidence = evidence
        return {
            "summary": "The API returned an unexpected status.",
            "observed_facts": ["Expected 200 and received 500."],
            "hypotheses": ["A server-side dependency may have failed."],
            "recommendations": ["Check server logs for the request."],
        }


class FailureAnalyzerTests(unittest.TestCase):
    def test_sends_only_minimal_execution_evidence_and_validates_output(self):
        provider = _FakeProvider()
        result = self._result(
            ExecutionOutcome.FAILED,
            response_body="private payload",
            response_headers={"Authorization": "Bearer secret"},
            error="private error detail",
        )

        analysis = analyze_failures([result], provider=provider)

        self.assertIsInstance(analysis, FailureAnalysis)
        self.assertEqual(analysis.observed_facts, ["Expected 200 and received 500."])
        serialized_evidence = json.dumps(provider.evidence)
        self.assertNotIn("private payload", serialized_evidence)
        self.assertNotIn("Bearer secret", serialized_evidence)
        self.assertNotIn("private error detail", serialized_evidence)
        self.assertEqual(provider.evidence["failures"][0]["actual_status"], 500)

    def test_rejects_analysis_when_there_are_no_failures(self):
        with self.assertRaisesRegex(ValueError, "no failed or errored tests"):
            analyze_failures([self._result(ExecutionOutcome.PASSED)], provider=_FakeProvider())

    def test_openai_provider_uses_responses_api_without_storing_input(self):
        provider = OpenAIResponsesProvider("test-key", "test-model")
        response_body = {
            "output": [{
                "type": "message",
                "content": [{
                    "type": "output_text",
                    "text": '{"summary":"ok","observed_facts":[],"hypotheses":[],"recommendations":[]}',
                }],
            }],
        }
        with patch("app.analysis.failure_analyzer.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(response_body).encode()

            response = provider.analyze({"failures": []})

        request = urlopen.call_args.args[0]
        request_data = json.loads(request.data.decode())
        self.assertEqual(request.full_url, OpenAIResponsesProvider.endpoint)
        self.assertFalse(request_data["store"])
        self.assertEqual(request_data["model"], "test-model")
        self.assertEqual(response["summary"], "ok")

    @staticmethod
    def _result(outcome, **kwargs):
        defaults = {
            "test_case": TestCase(
                name="fetch record",
                method="GET",
                path="/records/{id}",
                type="positive",
                path_params={"id": "sensitive-value"},
                headers={"Authorization": "Bearer test-secret"},
                expected_status=[200],
            ),
            "outcome": outcome,
            "actual_status": 500 if outcome == ExecutionOutcome.FAILED else None,
            "duration_ms": 15.0,
            "response_body": "private payload",
            "response_headers": {"Authorization": "Bearer secret"},
            "error": "private error detail",
        }
        defaults.update(kwargs)
        return TestExecutionResult(**defaults)


if __name__ == "__main__":
    unittest.main()
