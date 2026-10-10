import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.executor.http_executor import execute_batch, execute_batch_stream
from app.main import app
from app.models.execution_result import ExecutionOutcome, TestExecutionResult
from app.models.test_case import TestCase
from app.models.test_run import TestRunRequest


class TestPerformanceAndStreaming(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.cases = [
            TestCase(name=f"Case {i}", method="GET", path=f"/items/{i}", type="smoke", expected_status=[200])
            for i in range(5)
        ]

    def _mock_executor(self, case, base_url, **kwargs):
        idx = int(case.path.split("/")[-1])
        return TestExecutionResult(
            test_case=case,
            outcome=ExecutionOutcome.PASSED if idx % 2 == 0 else ExecutionOutcome.FAILED,
            actual_status=200 if idx % 2 == 0 else 500,
            duration_ms=10.0 + idx,
        )

    def test_execute_batch_preserves_order(self):
        results = execute_batch(
            self.cases,
            "http://127.0.0.1:8000",
            allowed_hosts={"127.0.0.1"},
            concurrency=3,
            allow_private_network=True,
            executor_fn=self._mock_executor,
        )
        self.assertEqual(len(results), 5)
        for i, res in enumerate(results):
            self.assertEqual(res.test_case.name, f"Case {i}")
            if i % 2 == 0:
                self.assertEqual(res.outcome, ExecutionOutcome.PASSED)
            else:
                self.assertEqual(res.outcome, ExecutionOutcome.FAILED)

    def test_execute_batch_handles_empty(self):
        results = execute_batch(
            [],
            "http://127.0.0.1:8000",
            allowed_hosts={"127.0.0.1"},
            concurrency=5,
        )
        self.assertEqual(results, [])

    def test_execute_batch_stream_yields_all_results(self):
        yielded = list(
            execute_batch_stream(
                self.cases,
                "http://127.0.0.1:8000",
                allowed_hosts={"127.0.0.1"},
                concurrency=4,
                allow_private_network=True,
                executor_fn=self._mock_executor,
            )
        )
        self.assertEqual(len(yielded), 5)
        indices = {idx for idx, _ in yielded}
        self.assertEqual(indices, {0, 1, 2, 3, 4})

    def test_run_stream_endpoint_produces_valid_sse(self):
        payload = {
            "test_cases": [case.model_dump() for case in self.cases[:3]],
            "base_url": "http://127.0.0.1:8000",
            "allowed_hosts": ["127.0.0.1"],
            "allow_private_network": True,
            "concurrency": 2,
        }

        with patch("app.api.test_runs.execute_test_case", side_effect=self._mock_executor):
            response = self.client.post("/run/stream", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])

        events = []
        for line in response.text.split("\n\n"):
            line = line.strip()
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))

        self.assertGreaterEqual(len(events), 4)  # 3 progress events + 1 complete event
        progress_events = [e for e in events if e.get("type") == "progress"]
        complete_events = [e for e in events if e.get("type") == "complete"]

        self.assertEqual(len(progress_events), 3)
        self.assertEqual(len(complete_events), 1)

        complete = complete_events[0]
        self.assertIn("report", complete)
        self.assertEqual(complete["report"]["summary"]["total_tests"], 3)


if __name__ == "__main__":
    unittest.main()
