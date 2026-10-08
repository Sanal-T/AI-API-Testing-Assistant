import json
import socket
import unittest
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

from app.executor.http_executor import execute_test_case
from app.models.execution_result import ExecutionErrorKind, ExecutionOutcome
from app.models.test_case import TestCase


class _FakeResponse:
    status = 201
    headers = {
        "Content-Type": "application/json",
        "Set-Cookie": "session=secret",
    }

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, limit):
        return b'{"created":true}'


class HttpExecutorTests(unittest.TestCase):
    base_url = "http://127.0.0.1:8000/api"

    @patch("app.executor.http_executor.build_opener")
    def test_substitutes_path_adds_query_and_compares_actual_status(self, build_opener):
        opener = build_opener.return_value
        opener.open.return_value = _FakeResponse()
        test_case = TestCase(
            name="get user",
            method="GET",
            path="/users/{user_id}",
            type="positive",
            path_params={"user_id": "a b"},
            query_params={"active": True},
            headers={"X-Test": "yes"},
            expected_status=[201],
        )

        result = execute_test_case(
            test_case,
            self.base_url,
            allowed_hosts={"127.0.0.1"},
            allow_private_network=True,
        )

        request = opener.open.call_args.args[0]
        self.assertEqual(result.actual_status, 201, result.error)
        self.assertEqual(result.outcome, ExecutionOutcome.PASSED)
        self.assertIn("/api/users/a%20b", request.full_url)
        self.assertEqual(parse_qs(urlsplit(request.full_url).query), {"active": ["True"]})
        self.assertEqual(request.get_header("X-test"), "yes")
        self.assertNotIn("Set-Cookie", result.response_headers)
        self.assertEqual(result.response_body, '{"created":true}')
        self.assertGreaterEqual(result.duration_ms, 0)

    @patch("app.executor.http_executor.build_opener")
    def test_sends_json_and_unknown_expectation_is_not_reported_as_pass(self, build_opener):
        opener = build_opener.return_value
        opener.open.return_value = _FakeResponse()
        test_case = TestCase(
            name="create item",
            method="POST",
            path="/items",
            type="positive",
            body={"name": "example"},
            expected_status=None,
        )

        result = execute_test_case(
            test_case,
            self.base_url,
            allowed_hosts={"127.0.0.1"},
            allow_private_network=True,
            allow_mutating_methods=True,
        )

        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(request.data), {"name": "example"})
        self.assertEqual(result.outcome, ExecutionOutcome.UNVERIFIED)

    @patch("app.executor.http_executor.build_opener")
    def test_requires_explicit_private_and_mutating_opt_ins(self, build_opener):
        test_case = TestCase(
            name="delete item",
            method="DELETE",
            path="/items/1",
            type="negative",
        )

        with self.assertRaisesRegex(ValueError, "allow_mutating_methods"):
            execute_test_case(
                test_case,
                self.base_url,
                allowed_hosts={"127.0.0.1"},
                allow_private_network=True,
            )

        safe_method = test_case.model_copy(update={"method": "GET"})
        with self.assertRaisesRegex(ValueError, "allow_private_network"):
            execute_test_case(safe_method, self.base_url, allowed_hosts={"127.0.0.1"})

        build_opener.assert_not_called()

    @patch("app.executor.http_executor.build_opener")
    def test_rejects_hosts_outside_the_configured_scope(self, build_opener):
        test_case = TestCase(
            name="out of scope",
            method="GET",
            path="/health",
            type="positive",
        )

        with self.assertRaisesRegex(ValueError, "allowlist"):
            execute_test_case(
                test_case,
                self.base_url,
                allowed_hosts={"api.example.com"},
                allow_private_network=True,
            )

        build_opener.assert_not_called()

    @patch("app.executor.http_executor.build_opener")
    def test_network_error_is_returned_without_fabricating_a_status(self, build_opener):
        opener = build_opener.return_value
        opener.open.side_effect = URLError("connection refused")
        test_case = TestCase(
            name="unavailable target",
            method="GET",
            path="/health",
            type="positive",
            expected_status=[200],
        )

        result = execute_test_case(
            test_case,
            self.base_url,
            allowed_hosts={"127.0.0.1"},
            allow_private_network=True,
        )

        self.assertIsNone(result.actual_status)
        self.assertEqual(result.outcome, ExecutionOutcome.ERROR)
        self.assertEqual(result.error_kind, ExecutionErrorKind.NETWORK)
        self.assertIn("connection refused", result.error)

    @patch("app.executor.http_executor.build_opener")
    def test_timeout_is_distinguished_from_other_network_errors(self, build_opener):
        opener = build_opener.return_value
        opener.open.side_effect = URLError(socket.timeout("timed out"))
        test_case = TestCase(
            name="slow target",
            method="GET",
            path="/health",
            type="positive",
            expected_status=[200],
        )

        result = execute_test_case(
            test_case,
            self.base_url,
            allowed_hosts={"127.0.0.1"},
            allow_private_network=True,
        )

        self.assertEqual(result.outcome, ExecutionOutcome.ERROR)
        self.assertEqual(result.error_kind, ExecutionErrorKind.TIMEOUT)

    @patch("app.executor.http_executor.build_opener")
    def test_known_status_mismatch_is_a_failed_assertion(self, build_opener):
        opener = build_opener.return_value
        opener.open.return_value = _FakeResponse()
        test_case = TestCase(
            name="expect different status",
            method="GET",
            path="/health",
            type="positive",
            expected_status=[200],
        )

        result = execute_test_case(
            test_case,
            self.base_url,
            allowed_hosts={"127.0.0.1"},
            allow_private_network=True,
        )

        self.assertEqual(result.outcome, ExecutionOutcome.FAILED)


if __name__ == "__main__":
    unittest.main()
