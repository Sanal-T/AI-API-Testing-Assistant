import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

from fastapi.testclient import TestClient

from app.cli import build_parser, main
from app.main import app
from app.models.execution_result import (
    ExecutionErrorKind,
    ExecutionOutcome,
    TestExecutionResult,
)
from app.models.test_case import TestCase
from app.report.exporters import (
    export_to_junit_xml,
    export_to_markdown_summary,
    export_to_postman_collection,
    export_to_pytest,
)


class TestCliAndExporters(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.sample_cases = [
            TestCase(
                name="Get Item 1",
                method="GET",
                path="/items/1",
                type="smoke",
                expected_status=[200],
            ),
            TestCase(
                name="Create Item",
                method="POST",
                path="/items",
                type="positive",
                expected_status=[201],
                body={"title": "Widget", "price": 9.99},
                headers={"X-Test": "True"},
            ),
        ]
        self.sample_results = [
            TestExecutionResult(
                test_case=self.sample_cases[0],
                outcome=ExecutionOutcome.PASSED,
                actual_status=200,
                duration_ms=45.2,
            ),
            TestExecutionResult(
                test_case=self.sample_cases[1],
                outcome=ExecutionOutcome.FAILED,
                actual_status=400,
                duration_ms=120.5,
                error="Expected status [201], but received 400",
            ),
            TestExecutionResult(
                test_case=TestCase(
                    name="Error Test",
                    method="GET",
                    path="/items/fail",
                    type="negative",
                    expected_status=[400],
                ),
                outcome=ExecutionOutcome.ERROR,
                actual_status=None,
                duration_ms=15.0,
                error="Network unreachable",
                error_kind=ExecutionErrorKind.NETWORK,
            ),
        ]

    def test_export_to_junit_xml(self):
        xml_str = export_to_junit_xml(self.sample_results, suite_name="Test Suite")
        self.assertTrue(xml_str.startswith("<?xml"))
        root = ElementTree.fromstring(xml_str)
        self.assertEqual(root.tag, "testsuites")
        self.assertEqual(root.attrib["tests"], "3")
        self.assertEqual(root.attrib["failures"], "1")
        self.assertEqual(root.attrib["errors"], "1")

        testcases = root.findall(".//testcase")
        self.assertEqual(len(testcases), 3)

        failed_case = next(tc for tc in testcases if tc.attrib["name"] == "Create Item")
        failure_elem = failed_case.find("failure")
        self.assertIsNotNone(failure_elem)
        self.assertIn("Expected status [201]", failure_elem.attrib["message"])

    def test_export_to_postman_collection(self):
        col = export_to_postman_collection(self.sample_cases, collection_name="Items API")
        self.assertEqual(col["info"]["name"], "Items API")
        self.assertEqual(
            col["info"]["schema"],
            "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        )
        self.assertGreaterEqual(len(col["item"]), 2)

    def test_export_to_pytest(self):
        code = export_to_pytest(self.sample_cases, base_url="https://api.example.com")
        self.assertIn("BASE_URL = \"https://api.example.com\"", code)
        self.assertIn("def test_000_get_item_1():", code)
        self.assertIn("def test_001_create_item():", code)
        # Verify valid syntax by compiling
        compiled = compile(code, "<string>", "exec")
        self.assertIsNotNone(compiled)

    def test_export_to_markdown_summary(self):
        report = {
            "summary": {
                "total_tests": 2,
                "counts": {"passed": 1, "failed": 1, "error": 0},
                "pass_rate": 0.5,
                "contract_violations": 0,
                "sla_violations": 0,
            },
            "by_endpoint": [
                {
                    "method": "GET",
                    "path": "/items",
                    "counts": {"passed": 1, "failed": 0, "error": 0},
                }
            ],
        }
        analysis = {
            "summary": "Root cause is 400 Bad Request.",
            "observed_facts": ["Endpoint rejected invalid payload"],
            "hypotheses": ["Validation rule too strict"],
            "recommendations": ["Check request schema"],
        }
        md = export_to_markdown_summary(report, analysis=analysis)
        self.assertIn("## 🧪 API Test Execution Summary", md)
        self.assertIn("| **Pass Rate** | **`50.0%`** |", md)
        self.assertIn("### 🤖 AI Failure Analysis", md)
        self.assertIn("Validation rule too strict", md)

    def test_export_api_endpoints(self):
        # Postman
        resp_pm = self.client.post(
            "/export/postman",
            json={"test_cases": [c.model_dump() for c in self.sample_cases]},
        )
        self.assertEqual(resp_pm.status_code, 200)
        self.assertIn("schema", resp_pm.json()["info"])

        # Pytest
        resp_py = self.client.post(
            "/export/pytest",
            json={"test_cases": [c.model_dump() for c in self.sample_cases]},
        )
        self.assertEqual(resp_py.status_code, 200)
        self.assertIn("def test_000", resp_py.text)

        # JUnit
        resp_ju = self.client.post(
            "/export/junit",
            json={"results": [r.model_dump(mode="json") for r in self.sample_results]},
        )
        self.assertEqual(resp_ju.status_code, 200)
        self.assertIn("<testsuites", resp_ju.text)

        # Markdown
        resp_md = self.client.post(
            "/export/markdown",
            json={"report": {"summary": {"total_tests": 1, "counts": {"passed": 1}}}},
        )
        self.assertEqual(resp_md.status_code, 200)
        self.assertIn("API Test Execution Summary", resp_md.text)

    def test_cli_export_command(self):
        spec_content = """
openapi: 3.0.0
info:
  title: Sample API
  version: 1.0.0
paths:
  /users:
    get:
      responses:
        '200':
          description: OK
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            spec_file = Path(tmpdir) / "openapi.yaml"
            spec_file.write_text(spec_content, encoding="utf-8")
            out_postman = Path(tmpdir) / "postman.json"

            code = main(["export", "--spec", str(spec_file), "--format", "postman", "--output", str(out_postman)])
            self.assertEqual(code, 0)
            self.assertTrue(out_postman.is_file())
            loaded = json.loads(out_postman.read_text(encoding="utf-8"))
            self.assertIn("info", loaded)

    def test_cli_run_command_success(self):
        spec_content = """
openapi: 3.0.0
info:
  title: Sample API
  version: 1.0.0
paths:
  /users:
    get:
      responses:
        '200':
          description: OK
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            spec_file = Path(tmpdir) / "openapi.yaml"
            spec_file.write_text(spec_content, encoding="utf-8")
            junit_out = Path(tmpdir) / "junit.xml"

            with patch("app.cli.execute_batch") as mock_exec:
                mock_exec.return_value = [
                    TestExecutionResult(
                        test_case=self.sample_cases[0],
                        outcome=ExecutionOutcome.PASSED,
                        actual_status=200,
                        duration_ms=10.0,
                    )
                ]
                exit_code = main([
                    "run",
                    "--spec", str(spec_file),
                    "--base-url", "http://127.0.0.1:8000",
                    "--output-junit", str(junit_out),
                ])
                self.assertEqual(exit_code, 0)
                self.assertTrue(junit_out.is_file())


if __name__ == "__main__":
    unittest.main()
