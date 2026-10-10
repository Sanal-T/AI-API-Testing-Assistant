import json
import unittest
from unittest.mock import MagicMock, patch

from app.api.workflows import generate_workflows_endpoint, run_workflow_endpoint
from app.executor.workflow_runner import (
    extract_variable_from_response,
    execute_workflow,
    resolve_placeholders,
)
from app.generator.workflow_generator import generate_crud_workflows
from app.models.execution_result import ExecutionOutcome, TestExecutionResult
from app.models.test_case import TestCase
from app.models.workflow import (
    VariableExtractor,
    Workflow,
    WorkflowRunRequest,
    WorkflowStep,
)


class WorkflowRunnerTests(unittest.TestCase):
    def test_resolve_placeholders_replaces_strings_and_structures(self):
        context = {
            "user_id": 105,
            "token": "secret_jwt_xyz",
            "active": True,
        }

        # Exact match retains native types
        self.assertEqual(resolve_placeholders("{{user_id}}", context), 105)
        self.assertEqual(resolve_placeholders("{{active}}", context), True)

        # Embedded string interpolation
        self.assertEqual(
            resolve_placeholders("Bearer {{token}}", context),
            "Bearer secret_jwt_xyz",
        )
        self.assertEqual(
            resolve_placeholders("/users/{{user_id}}/profile", context),
            "/users/105/profile",
        )

        # Recursive dict and list interpolation
        complex_payload = {
            "auth": "Bearer {{token}}",
            "owner": "{{user_id}}",
            "tags": ["user-{{user_id}}", "verified"],
        }
        resolved = resolve_placeholders(complex_payload, context)
        self.assertEqual(resolved["auth"], "Bearer secret_jwt_xyz")
        self.assertEqual(resolved["owner"], 105)
        self.assertEqual(resolved["tags"], ["user-105", "verified"])

    def test_extract_variable_from_response_body_and_headers(self):
        dummy_case = TestCase(name="dummy", method="GET", path="/", type="positive")
        result = TestExecutionResult(
            test_case=dummy_case,
            outcome=ExecutionOutcome.PASSED,
            actual_status=200,
            response_headers={"Location": "/items/99", "X-Request-Id": "req_123"},
            response_body=json.dumps({"data": {"id": 99, "role": "admin"}, "token": "auth_abc"}),
            duration_ms=20.0,
        )

        # Extract from body
        ext_id = VariableExtractor(source="body", path="data.id", variable_name="item_id")
        self.assertEqual(extract_variable_from_response(ext_id, result), 99)

        ext_token = VariableExtractor(source="body", path="token", variable_name="jwt")
        self.assertEqual(extract_variable_from_response(ext_token, result), "auth_abc")

        # Extract from header
        ext_header = VariableExtractor(source="header", path="X-Request-Id", variable_name="trace_id")
        self.assertEqual(extract_variable_from_response(ext_header, result), "req_123")

    def test_execute_workflow_chains_variables_and_runs_teardown(self):
        step1_case = TestCase(
            name="Create Item",
            method="POST",
            path="/items",
            type="positive",
            body={"name": "Book"},
        )
        step2_case = TestCase(
            name="Get Item",
            method="GET",
            path="/items/{id}",
            type="positive",
            path_params={"id": "{{created_id}}"},
            headers={"Authorization": "Bearer {{auth_token}}"},
        )
        teardown_case = TestCase(
            name="Delete Item",
            method="DELETE",
            path="/items/{id}",
            type="positive",
            path_params={"id": "{{created_id}}"},
        )

        workflow = Workflow(
            name="Item Lifecycle",
            initial_variables={"auth_token": "init_token"},
            steps=[
                WorkflowStep(
                    id="step1",
                    name="Step 1: Create",
                    test_case=step1_case,
                    extract_variables=[
                        VariableExtractor(source="body", path="id", variable_name="created_id")
                    ],
                ),
                WorkflowStep(
                    id="step2",
                    name="Step 2: Get",
                    test_case=step2_case,
                ),
            ],
            teardown_steps=[
                WorkflowStep(
                    id="td1",
                    name="Teardown: Delete",
                    test_case=teardown_case,
                )
            ],
        )

        # Mock execute_test_case
        def fake_executor(test_case, base_url, **kwargs):
            if test_case.method == "POST":
                return TestExecutionResult(
                    test_case=test_case,
                    outcome=ExecutionOutcome.PASSED,
                    actual_status=201,
                    response_body='{"id": "item_888"}',
                    duration_ms=30.0,
                )
            elif test_case.method == "GET":
                # Verify that {{created_id}} was resolved to 'item_888'
                assert test_case.path_params.get("id") == "item_888"
                assert test_case.headers.get("Authorization") == "Bearer init_token"
                return TestExecutionResult(
                    test_case=test_case,
                    outcome=ExecutionOutcome.PASSED,
                    actual_status=200,
                    response_body='{"id": "item_888", "name": "Book"}',
                    duration_ms=25.0,
                )
            elif test_case.method == "DELETE":
                assert test_case.path_params.get("id") == "item_888"
                return TestExecutionResult(
                    test_case=test_case,
                    outcome=ExecutionOutcome.PASSED,
                    actual_status=204,
                    duration_ms=15.0,
                )
            return TestExecutionResult(test_case=test_case, outcome=ExecutionOutcome.ERROR, duration_ms=0)

        with patch("app.executor.workflow_runner.execute_test_case", side_effect=fake_executor):
            res = execute_workflow(
                workflow=workflow,
                base_url="https://api.example.com",
                allowed_hosts={"api.example.com"},
            )

        self.assertTrue(res.passed)
        self.assertEqual(len(res.step_results), 2)
        self.assertEqual(len(res.teardown_results), 1)
        self.assertEqual(res.context_variables["created_id"], "item_888")

    def test_generate_crud_workflows_synthesizes_crud_lifecycle(self):
        endpoints = [
            {
                "method": "POST",
                "path": "/products",
                "summary": "Create Product",
                "resolved_schema": {"type": "object", "properties": {"name": {"type": "string"}}},
                "responses": {"201": {}},
            },
            {
                "method": "GET",
                "path": "/products/{id}",
                "summary": "Get Product",
                "parameters": [{"name": "id", "location": "path", "required": True}],
                "responses": {"200": {}},
            },
            {
                "method": "DELETE",
                "path": "/products/{id}",
                "summary": "Delete Product",
                "parameters": [{"name": "id", "location": "path", "required": True}],
                "responses": {"204": {}},
            },
        ]

        workflows = generate_crud_workflows(endpoints)
        self.assertEqual(len(workflows), 1)
        wf = workflows[0]
        self.assertIn("Products", wf.name)
        self.assertEqual(len(wf.steps), 2)  # Create and Get
        self.assertEqual(len(wf.teardown_steps), 1)  # Delete
        self.assertEqual(wf.steps[0].test_case.method, "POST")
        self.assertEqual(wf.steps[1].test_case.method, "GET")
        self.assertEqual(wf.teardown_steps[0].test_case.method, "DELETE")

    def test_api_workflows_endpoints(self):
        # 1. Generate endpoint
        gen_res = generate_workflows_endpoint(
            MagicMock(endpoints=[
                {"method": "POST", "path": "/widgets", "responses": {"201": {}}},
                {"method": "GET", "path": "/widgets/{id}", "parameters": [{"name": "id", "location": "path"}], "responses": {"200": {}}},
            ])
        )
        self.assertEqual(gen_res["total"], 1)

        # 2. Run endpoint
        step_case = TestCase(name="health", method="GET", path="/health", type="positive")
        wf = Workflow(name="Health WF", steps=[WorkflowStep(id="s1", name="health", test_case=step_case)])
        req = WorkflowRunRequest(workflow=wf, base_url="http://127.0.0.1:8000", allowed_hosts={"127.0.0.1"})

        with patch("app.api.workflows.execute_workflow") as mock_exec:
            mock_exec.return_value = MagicMock(
                workflow_name="Health WF",
                passed=True,
                duration_ms=50.0,
                context_variables={},
                error=None,
                step_results=[],
                teardown_results=[],
            )
            run_res = run_workflow_endpoint(req)
            self.assertEqual(run_res["workflow_name"], "Health WF")
            self.assertTrue(run_res["passed"])


if __name__ == "__main__":
    unittest.main()
