import unittest

from app.generator.testcase_generator import (
    generate_negative_tests,
    generate_test_cases,
    generate_valid_payload,
)
from app.models.test_case import TestCase


class GenerateTestCasesTests(unittest.TestCase):
    def test_generates_nested_and_string_length_negative_cases(self):
        schema = {
            "type": "object",
            "properties": {
                "profile": {
                    "type": "object",
                    "required": ["nickname"],
                    "properties": {
                        "nickname": {"type": "string", "minLength": 3, "maxLength": 8},
                    },
                },
            },
        }

        payload = generate_valid_payload(schema)
        cases = generate_negative_tests(schema)
        by_name = {case["name"]: case["payload"] for case in cases}

        self.assertGreaterEqual(len(payload["profile"]["nickname"]), 3)
        self.assertEqual(by_name["Missing required field: profile.nickname"]["profile"], {})
        self.assertEqual(by_name["Below minimum length: profile.nickname"]["profile"]["nickname"], "xx")
        self.assertEqual(len(by_name["Above maximum length: profile.nickname"]["profile"]["nickname"]), 9)

    def test_generates_enum_and_array_item_and_size_negative_cases(self):
        schema = {
            "type": "object",
            "properties": {
                "codes": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 2,
                    "items": {"type": "integer", "enum": [1, 2]},
                },
            },
        }

        cases = generate_negative_tests(schema)
        by_name = {case["name"]: case["payload"]["codes"] for case in cases}

        self.assertEqual(by_name["Below minimum array size: codes"], [])
        self.assertEqual(len(by_name["Above maximum array size: codes"]), 3)
        self.assertNotIn(1, by_name["Invalid enum value: codes.item"])

    def test_generates_nested_objects_arrays_and_numbers(self):
        schema = {
            "type": "object",
            "properties": {
                "price": {"type": "number", "minimum": 1.5},
                "profile": {
                    "type": "object",
                    "properties": {
                        "email": {"type": "string", "format": "email"},
                    },
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["blue", "green"]},
                    "minItems": 2,
                },
            },
        }

        payload = generate_valid_payload(schema)

        self.assertEqual(payload, {
            "price": 1.5,
            "profile": {"email": "john@example.com"},
            "labels": ["blue", "blue"],
        })

    def test_generates_number_boundary_cases(self):
        schema = {
            "type": "object",
            "properties": {
                "score": {"type": "number", "minimum": 1.5, "maximum": 2.5},
            },
        }

        tests = generate_negative_tests(schema)
        below_minimum = next(test for test in tests if test["name"] == "score below minimum")
        above_maximum = next(test for test in tests if test["name"] == "score above maximum")

        self.assertEqual(below_minimum["payload"]["score"], 0.5)
        self.assertEqual(above_maximum["payload"]["score"], 3.5)

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
                "required": True,
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
            "responses": {"201": {}, "400": {}, "422": {}, "default": {}},
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
        self.assertEqual(missing_required.expected_status, [400, 422])
        self.assertEqual(empty_body.body, {})
        self.assertEqual(empty_body.expected_status, [400, 422])

    def test_validation_expectation_is_unknown_when_no_matching_status_is_documented(self):
        endpoint = {
            "method": "POST",
            "path": "/users",
            "parameters": [],
            "request_body": {
                "content": {"application/json": {"schema": {"type": "object", "required": ["name"]}}}
            },
            "resolved_schema": {"type": "object", "required": ["name"]},
            "responses": {"201": {}, "409": {}},
        }

        cases = generate_test_cases(endpoint)
        negative = next(case for case in cases if case.name == "Missing required field: name")

        self.assertIsNone(negative.expected_status)

    def test_success_expectation_is_unknown_without_a_documented_numeric_2xx_status(self):
        endpoint = {
            "method": "GET",
            "path": "/users",
            "parameters": [],
            "request_body": {},
            "resolved_schema": {},
            "responses": {"default": {}, "2XX": {}},
        }

        cases = generate_test_cases(endpoint)

        self.assertIsNone(cases[0].expected_status)

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

    def test_optional_request_body_adds_omission_case_without_empty_body_negative(self):
        endpoint = {
            "method": "POST",
            "path": "/items",
            "parameters": [],
            "request_body": {
                "required": False,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                            "required": ["name"],
                        }
                    }
                },
            },
            "request_body_required": False,
            "resolved_schema": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            "responses": {"201": {}, "422": {}},
        }

        cases = generate_test_cases(endpoint)
        omitted = next(case for case in cases if case.name.startswith("Omit optional request body"))

        self.assertIsNone(omitted.body)
        self.assertEqual(omitted.type, "positive")
        self.assertFalse(any(case.name == "Empty request body" for case in cases))
        self.assertTrue(any(case.name == "Missing required field: name" for case in cases))


if __name__ == "__main__":
    unittest.main()
