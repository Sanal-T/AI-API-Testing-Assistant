import unittest

from app.generator.testcase_generator import generate_test_cases
from app.models.test_case import TestCase


class GenerateTestCasesTests(unittest.TestCase):
    def test_converts_endpoint_data_without_mixing_request_parts(self):
        endpoint = {
            "method": "POST",
            "path": "/users/{user_id}",
            "parameters": [
                {"name": "user_id", "location": "path", "schema": {"type": "integer"}},
                {"name": "active", "location": "query", "schema": {"type": "boolean"}},
                {"name": "X-Trace", "location": "header", "schema": {"type": "string"}},
            ],
            "request_body": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                            "required": ["name"],
                        }
                    }
                }
            },
            "resolved_schema": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            "responses": {"201": {}, "400": {}, "default": {}},
        }

        cases = generate_test_cases(endpoint)
        positive = cases[0]
        missing_required = next(case for case in cases if case.name == "Missing required field: name")
        empty_body = next(case for case in cases if case.name == "Empty request body")

        self.assertTrue(all(isinstance(case, TestCase) for case in cases))
        self.assertEqual(positive.method, "POST")
        self.assertEqual(positive.path_params, {"user_id": 1})
        self.assertEqual(positive.query_params, {"active": True})
        self.assertEqual(positive.headers, {"X-Trace": "test-value"})
        self.assertEqual(positive.body, {"name": "sample"})
        self.assertEqual(positive.expected_status, [201])
        self.assertEqual(missing_required.body, {})
        self.assertEqual(missing_required.expected_status, [])
        self.assertEqual(empty_body.body, {})

    def test_bodyless_endpoint_gets_no_body_or_negative_body_cases(self):
        endpoint = {
            "method": "GET",
            "path": "/users/{user_id}",
            "parameters": [
                {"name": "user_id", "location": "path", "schema": {"type": "integer"}},
            ],
            "request_body": {},
            "resolved_schema": {},
            "responses": {"200": {"description": "ok"}},
        }

        cases = generate_test_cases(endpoint)

        self.assertEqual(len(cases), 1)
        self.assertIsNone(cases[0].body)
        self.assertEqual(cases[0].expected_status, [200])
        self.assertEqual(cases[0].path_params, {"user_id": 1})


if __name__ == "__main__":
    unittest.main()
