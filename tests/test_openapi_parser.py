import unittest

from app.parser.openapi_parser import extract_endpoints, resolve_schema_ref


class OpenApiParameterParsingTests(unittest.TestCase):
    def test_resolves_references_inside_nested_properties_and_array_items(self):
        spec = {
            "components": {
                "schemas": {
                    "User/Profile": {
                        "type": "object",
                        "properties": {
                            "profile": {"$ref": "#/components/schemas/Profile"},
                            "emails": {
                                "type": "array",
                                "items": {"$ref": "#/components/schemas/Email"},
                            },
                        },
                    },
                    "Profile": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    },
                    "Email": {"type": "string", "format": "email"},
                    "LiteralReferenceValue": {
                        "type": "object",
                        "properties": {
                            "payload": {"default": {"$ref": "literal user data"}},
                        },
                    },
                }
            }
        }

        resolved = resolve_schema_ref(
            spec,
            {"$ref": "#/components/schemas/User~1Profile"},
        )

        self.assertEqual(resolved["properties"]["profile"]["properties"]["name"]["type"], "string")
        self.assertEqual(resolved["properties"]["emails"]["items"]["format"], "email")
        self.assertNotIn("$ref", resolved["properties"]["profile"])
        literal = resolve_schema_ref(
            spec,
            {"$ref": "#/components/schemas/LiteralReferenceValue"},
        )
        self.assertEqual(
            literal["properties"]["payload"]["default"],
            {"$ref": "literal user data"},
        )

    def test_reports_unresolved_external_and_circular_references(self):
        with self.assertRaisesRegex(ValueError, "Unresolved schema reference"):
            resolve_schema_ref({}, {"$ref": "#/components/schemas/Missing"})

        with self.assertRaisesRegex(ValueError, "Only local JSON Pointer references"):
            resolve_schema_ref({}, {"$ref": "https://example.com/schema.json"})

        recursive_spec = {
            "components": {
                "schemas": {
                    "Node": {
                        "type": "object",
                        "properties": {"parent": {"$ref": "#/components/schemas/Node"}},
                    }
                }
            }
        }
        with self.assertRaisesRegex(ValueError, "Circular schema reference"):
            resolve_schema_ref(recursive_spec, {"$ref": "#/components/schemas/Node"})

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
