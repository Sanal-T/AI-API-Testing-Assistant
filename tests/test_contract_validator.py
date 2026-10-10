import json
import unittest
from unittest.mock import MagicMock, patch

from app.executor.contract_validator import validate_response_contract
from app.executor.http_executor import execute_test_case
from app.models.execution_result import ExecutionOutcome
from app.models.test_case import TestCase


class ContractValidatorTests(unittest.TestCase):
    def setUp(self):
        self.user_schema = {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "username": {"type": "string"},
                "email": {"type": "string"},
            },
            "required": ["id", "username", "email"],
        }

    def test_valid_json_matching_schema_passes_validation(self):
        test_case = TestCase(
            name="Get User",
            method="GET",
            path="/users/1",
            type="positive",
            expected_status=[200],
            expected_response_schema=self.user_schema,
        )
        valid_body = json.dumps({"id": 1, "username": "alice", "email": "alice@example.com"})

        result = validate_response_contract(
            test_case=test_case,
            status_code=200,
            response_headers={"content-type": "application/json"},
            response_body_str=valid_body,
            duration_ms=120.0,
        )

        self.assertTrue(result.is_valid)
        self.assertTrue(result.schema_passed)
        self.assertEqual(result.schema_errors, [])

    def test_schema_drift_fails_when_required_property_is_missing(self):
        test_case = TestCase(
            name="Get User",
            method="GET",
            path="/users/1",
            type="positive",
            expected_status=[200],
            expected_response_schema=self.user_schema,
        )
        # Missing 'email'
        drifted_body = json.dumps({"id": 1, "username": "alice"})

        result = validate_response_contract(
            test_case=test_case,
            status_code=200,
            response_headers={"content-type": "application/json"},
            response_body_str=drifted_body,
            duration_ms=120.0,
        )

        self.assertFalse(result.is_valid)
        self.assertFalse(result.schema_passed)
        self.assertTrue(any("email" in err for err in result.schema_errors))

    def test_schema_drift_fails_when_property_type_is_wrong(self):
        test_case = TestCase(
            name="Get User",
            method="GET",
            path="/users/1",
            type="positive",
            expected_status=[200],
            expected_response_schema=self.user_schema,
        )
        # 'id' is string instead of integer
        invalid_type_body = json.dumps({"id": "not-an-int", "username": "alice", "email": "a@b.com"})

        result = validate_response_contract(
            test_case=test_case,
            status_code=200,
            response_headers={"content-type": "application/json"},
            response_body_str=invalid_type_body,
            duration_ms=120.0,
        )

        self.assertFalse(result.is_valid)
        self.assertFalse(result.schema_passed)
        self.assertTrue(any("id" in err for err in result.schema_errors))

    def test_header_assertions_pass_and_fail(self):
        test_case = TestCase(
            name="Check Headers",
            method="GET",
            path="/api",
            type="positive",
            expected_headers={"Content-Type": "application/json", "X-Custom": "secure"},
        )

        # Fails when X-Custom is missing
        result_missing = validate_response_contract(
            test_case=test_case,
            status_code=200,
            response_headers={"content-type": "application/json"},
            response_body_str="{}",
            duration_ms=50.0,
        )
        self.assertFalse(result_missing.is_valid)
        self.assertTrue(any("X-Custom" in err for err in result_missing.header_errors))

        # Passes when both are present
        result_ok = validate_response_contract(
            test_case=test_case,
            status_code=200,
            response_headers={"content-type": "application/json; charset=utf-8", "x-custom": "secure"},
            response_body_str="{}",
            duration_ms=50.0,
        )
        self.assertTrue(result_ok.is_valid)

    def test_json_path_deep_assertions(self):
        test_case = TestCase(
            name="Check Payload Values",
            method="GET",
            path="/status",
            type="positive",
            json_path_assertions=[
                {"path": "data.status", "equals": "active"},
                {"path": "data.items", "min_count": 2},
                {"path": "meta.token", "exists": True},
            ],
        )

        payload_ok = json.dumps({
            "data": {"status": "active", "items": ["a", "b", "c"]},
            "meta": {"token": "xyz123"},
        })
        result_ok = validate_response_contract(
            test_case=test_case,
            status_code=200,
            response_headers={},
            response_body_str=payload_ok,
            duration_ms=10.0,
        )
        self.assertTrue(result_ok.is_valid)

        payload_mismatch = json.dumps({
            "data": {"status": "inactive", "items": ["a"]},
            "meta": {},
        })
        result_bad = validate_response_contract(
            test_case=test_case,
            status_code=200,
            response_headers={},
            response_body_str=payload_mismatch,
            duration_ms=10.0,
        )
        self.assertFalse(result_bad.is_valid)
        self.assertEqual(len(result_bad.assertion_errors), 3)

    def test_sla_latency_threshold_fails_when_exceeded(self):
        test_case = TestCase(
            name="Fast Endpoint",
            method="GET",
            path="/fast",
            type="positive",
            max_duration_ms=200.0,
        )

        # 150ms <= 200ms -> passes
        res_ok = validate_response_contract(
            test_case=test_case,
            status_code=200,
            response_headers={},
            response_body_str="{}",
            duration_ms=150.0,
        )
        self.assertTrue(res_ok.is_valid)
        self.assertFalse(res_ok.sla_exceeded)

        # 350ms > 200ms -> SLA breached
        res_slow = validate_response_contract(
            test_case=test_case,
            status_code=200,
            response_headers={},
            response_body_str="{}",
            duration_ms=350.0,
        )
        self.assertFalse(res_slow.is_valid)
        self.assertTrue(res_slow.sla_exceeded)

    def test_execute_test_case_fails_200_ok_when_schema_drifts(self):
        test_case = TestCase(
            name="Get User with Schema Drift",
            method="GET",
            path="/users/1",
            type="positive",
            expected_status=[200],
            expected_response_schema=self.user_schema,
        )

        # Fake response: returns 200 OK, but response body lacks required fields
        fake_response = MagicMock()
        fake_response.status = 200
        fake_response.headers = {"Content-Type": "application/json"}
        fake_response.read.return_value = b'{"wrong_key": "drifted"}'

        with patch("urllib.request.OpenerDirector.open", return_value=fake_response):
            result = execute_test_case(
                test_case,
                "https://api.example.com",
                allowed_hosts={"api.example.com"},
            )

        self.assertEqual(result.actual_status, 200)
        self.assertEqual(result.outcome, ExecutionOutcome.FAILED)
        self.assertFalse(result.schema_validation_passed)
        self.assertIn("Schema drift", str(result.error))


if __name__ == "__main__":
    unittest.main()
