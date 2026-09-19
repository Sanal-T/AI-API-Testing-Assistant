import unittest

from app.generator.testcase_generator import (
    generate_negative_tests,
    generate_test_cases,
    generate_valid_payload,
)
from app.models.test_case import TestCase


class GenerateTestCasesTests(unittest.TestCase):
    def test_honors_openapi_30_exclusive_bounds_and_nullability(self):
        schema = {
            "type": "object",
            "properties": {
                "score": {
                    "type": "integer",
                    "minimum": 2,
                    "maximum": 10,
                    "exclusiveMinimum": True,
                    "exclusiveMaximum": True,
                },
                "nickname": {"type": "string", "nullable": True},
                "required_label": {"type": "string"},
            },
        }

        payload = generate_valid_payload(schema)
        cases = generate_negative_tests(schema)
        case_names = {case["name"] for case in cases}

        self.assertEqual(payload["score"], 3)
        self.assertIsNone(payload["nickname"])
        self.assertIn("At exclusive minimum: score", case_names)
        self.assertIn("At exclusive maximum: score", case_names)
        self.assertIn("Null value for non-nullable field: required_label", case_names)
        self.assertNotIn("Null value for non-nullable field: nickname", case_names)

    def test_generates_invalid_query_cases_and_missing_authentication_case(self):
        endpoint = {
            "method": "GET",
            "path": "/users",
            "parameters": [
                {"name": "page", "location": "query", "required": True,
                 "schema": {"type": "integer", "minimum": 1, "maximum": 5}},
                {"name": "role", "location": "query",
                 "schema": {"type": "string", "enum": ["member", "admin"]}},
            ],
            "request_body": {},
            "resolved_schema": {},
            "responses": {"200": {}, "400": {}, "401": {}, "403": {}, "422": {}},
            "security_requirements": [{"BearerAuth": []}],
            "security_schemes": {"BearerAuth": {"type": "http", "scheme": "bearer"}},
        }

        cases = generate_test_cases(endpoint)
        by_name = {case.name: case for case in cases}

        self.assertEqual(by_name["Valid request: GET /users"].headers["Authorization"], "Bearer test-token")
        self.assertEqual(by_name["page below minimum"].query_params["page"], 0)
        self.assertEqual(by_name["Missing required parameter: page"].expected_status, [400, 422])
        self.assertIn("page", by_name["Missing required parameter: page"].request_query_exclusions)
        self.assertEqual(by_name["Invalid enum value: role"].query_params["role"], "__invalid_enum_value__")
        missing_auth = by_name["Missing authentication: GET /users"]
        self.assertNotIn("Authorization", missing_auth.headers)
        self.assertIn("authorization", missing_auth.request_header_exclusions)
        self.assertEqual(missing_auth.expected_status, [401, 403])

    def test_generates_payloads_for_composed_nullable_and_formatted_schemas(self):
        schema = {
            "type": "object",
            "allOf": [
                {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string", "minLength": 4},
                        "rating": {"type": "integer", "minimum": 1, "maximum": 10},
                    },
                },
                {
                    "type": "object",
                    "required": ["id"],
                    "properties": {
                        "id": {"oneOf": [
                            {"type": "integer", "minimum": 2},
                            {"type": "string"},
                        ]},
                        "rating": {"type": "integer", "minimum": 4, "maximum": 8},
                    },
                },
            ],
            "properties": {
                "contact": {"type": "string", "format": "email"},
                "optional_note": {"type": "string", "nullable": True},
            },
        }

        payload = generate_valid_payload(schema)
        self.assertGreaterEqual(len(payload["name"]), 4)
        self.assertEqual(payload["id"], 2)
        self.assertEqual(payload["rating"], 4)
        self.assertEqual(payload["contact"], "john@example.com")
        self.assertIsNone(payload["optional_note"])

        cases = generate_negative_tests(schema)
        self.assertTrue(any(case["name"] == "Missing required field: name" for case in cases))
        self.assertTrue(any(case["name"] == "Missing required field: id" for case in cases))
        below_minimum = next(case for case in cases if case["name"] == "rating below minimum")
        self.assertEqual(below_minimum["payload"]["rating"], 3)

    def test_generates_examples_and_negative_cases_for_common_string_formats(self):
        schema = {
            "type": "object",
            "properties": {
                "id": {"type": "string", "format": "uuid"},
                "created": {"type": "string", "format": "date-time"},
            },
        }

        payload = generate_valid_payload(schema)
        case_names = {case["name"] for case in generate_negative_tests(schema)}

        self.assertEqual(payload["id"], "123e4567-e89b-12d3-a456-426614174000")
        self.assertEqual(payload["created"], "2030-01-02T03:04:05Z")
        self.assertIn("Invalid uuid format: id", case_names)
        self.assertIn("Invalid date-time format: created", case_names)

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
