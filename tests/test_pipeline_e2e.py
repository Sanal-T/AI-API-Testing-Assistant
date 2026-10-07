import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import unittest

from app.executor.http_executor import execute_test_case
from app.generator.testcase_generator import generate_test_cases
from app.models.execution_result import ExecutionOutcome
from app.parser.openapi_parser import extract_endpoints, load_spec


class _LocalApiFixture(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/mismatch":
            self._send_json(418, {"error": "intentional status mismatch"})
        elif self.path == "/health":
            self._send_json(200, {"status": "ok"})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(content_length) or b"{}")
        if isinstance(body, dict) and body.get("name"):
            self._send_json(201, {"created": True, "name": body["name"]})
        else:
            self._send_json(422, {"error": "name is required"})

    def _send_json(self, status, payload):
        response = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format, *args):
        pass


class PipelineEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _LocalApiFixture)
        cls.server_thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join()

    def test_parse_generate_execute_and_classify_results(self):
        spec_path = Path(__file__).parent / "fixtures" / "e2e_openapi.yaml"
        spec = load_spec(spec_path)
        endpoints = extract_endpoints(spec)
        generated = [
            (endpoint, test_case)
            for endpoint in endpoints
            for test_case in generate_test_cases(endpoint)
        ]

        results = [
            execute_test_case(
                test_case,
                self.base_url,
                allowed_hosts={"127.0.0.1"},
                allow_private_network=True,
                allow_mutating_methods=True,
            )
            for _, test_case in generated
        ]

        self.assertEqual(len(generated), 5)
        self.assertEqual(
            [result.outcome for result in results].count(ExecutionOutcome.PASSED),
            4,
        )
        self.assertEqual(
            [result.outcome for result in results].count(ExecutionOutcome.FAILED),
            1,
        )

        mismatch = next(result for result in results if result.test_case.path == "/mismatch")
        self.assertEqual(mismatch.actual_status, 418)
        self.assertEqual(mismatch.test_case.expected_status, [200])

        item_results = [result for result in results if result.test_case.path == "/items"]
        self.assertEqual(
            {result.actual_status for result in item_results},
            {201, 422},
        )
        self.assertTrue(all(result.error is None for result in results))


if __name__ == "__main__":
    unittest.main()
