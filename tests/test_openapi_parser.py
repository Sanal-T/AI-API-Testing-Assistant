import unittest

from app.parser.openapi_parser import extract_endpoints


class OpenApiParameterParsingTests(unittest.TestCase):
    def test_extracts_request_body_required_flag_and_defaults_to_optional(self):
        spec = {
            "paths": {
                "/items": {
                    "post": {
                        "requestBody": {
                            "required": True,
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        },
                        "responses": {"201": {}},
                    },
                    "patch": {
                        "requestBody": {
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        },
                        "responses": {"200": {}},
                    },
                }
            }
        }

        endpoints = extract_endpoints(spec)

        self.assertTrue(endpoints[0]["request_body_required"])
        self.assertFalse(endpoints[1]["request_body_required"])

    def test_inherits_path_parameters_and_applies_operation_overrides(self):
        spec = {
            "paths": {
                "/users/{user_id}": {
                    "parameters": [
                        {
                            "name": "user_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer"},
                        },
                        {
                            "name": "status",
                            "in": "query",
                            "schema": {"type": "string"},
                        },
                    ],
                    "get": {
                        "parameters": [
                            {
                                "name": "status",
                                "in": "query",
                                "schema": {"type": "string", "enum": ["active", "disabled"]},
                            },
                            {
                                "name": "X-Trace",
                                "in": "header",
                                "schema": {"type": "string"},
                            },
                        ],
                        "responses": {"200": {"description": "ok"}},
                    },
                    "delete": {
                        "responses": {"204": {"description": "deleted"}},
                    },
                }
            }
        }

        endpoints = extract_endpoints(spec)
        get_parameters = endpoints[0]["parameters"]
        delete_parameters = endpoints[1]["parameters"]
        get_by_key = {(item["name"], item["location"]): item for item in get_parameters}

        self.assertEqual(len(get_parameters), 3)
        self.assertEqual(get_by_key[("user_id", "path")]["required"], True)
        self.assertEqual(
            get_by_key[("status", "query")]["schema"],
            {"type": "string", "enum": ["active", "disabled"]},
        )
        self.assertIn(("X-Trace", "header"), get_by_key)
        self.assertEqual(len(delete_parameters), 2)
        self.assertEqual(delete_parameters[0]["name"], "user_id")
        self.assertEqual(delete_parameters[1]["name"], "status")


if __name__ == "__main__":
    unittest.main()
