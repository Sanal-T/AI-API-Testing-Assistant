import unittest

from app.parser.openapi_parser import extract_endpoints, resolve_schema_ref


class OpenApiParameterParsingTests(unittest.TestCase):
    def test_extracts_effective_server_urls_with_openapi_override_order(self):
        spec = {
            "servers": [{"url": "https://global.example/v1"}],
            "paths": {
                "/global": {
                    "get": {"responses": {"200": {}}},
                },
                "/path": {
                    "servers": [{"url": "https://path.example/api"}],
                    "get": {"responses": {"200": {}}},
                },
                "/operation": {
                    "servers": [{"url": "https://path.example/api"}],
                    "get": {
                        "servers": [{"url": "https://{region}.example/api"}],
                        "responses": {"200": {}},
                    },
                },
            },
        }

        endpoints = extract_endpoints(spec)

        self.assertEqual(endpoints[0]["server_urls"], ["https://global.example/v1"])
        self.assertEqual(endpoints[1]["server_urls"], ["https://path.example/api"])
        self.assertEqual(endpoints[2]["server_urls"], ["https://{region}.example/api"])

    def test_uses_openapi_default_relative_server_when_none_are_declared(self):
        endpoint = extract_endpoints({"paths": {"/health": {"get": {}}}})[0]

        self.assertEqual(endpoint["server_urls"], ["/"])

    def test_extracts_request_schemas_for_each_content_type(self):
        spec = {
            "components": {
                "schemas": {
                    "Item": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    },
                }
            },
            "paths": {
                "/items": {
                    "post": {
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Item"},
                                },
                                "application/x-www-form-urlencoded": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"quantity": {"type": "integer"}},
                                    },
                                },
                                "text/plain": {"example": "unused because no schema is declared"},
                            },
                        },
                        "responses": {"201": {"description": "created"}},
                    }
                }
            },
        }

        endpoint = extract_endpoints(spec)[0]

        self.assertEqual(
            endpoint["request_body_schemas"]["application/json"]["properties"]["name"]["type"],
            "string",
        )
        self.assertEqual(
            endpoint["request_body_schemas"]["application/x-www-form-urlencoded"]["properties"]["quantity"]["type"],
            "integer",
        )
        self.assertNotIn("text/plain", endpoint["request_body_schemas"])
        self.assertEqual(endpoint["resolved_schema"], endpoint["request_body_schemas"]["application/json"])

    def test_extracts_response_schemas_by_status_and_media_type(self):
        spec = {
            "components": {
                "schemas": {
                    "User": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    },
                }
            },
            "paths": {
                "/users/{user_id}": {
                    "get": {
                        "responses": {
                            "200": {
                                "description": "User found",
                                "content": {
                                    "application/json": {
                                        "schema": {"$ref": "#/components/schemas/User"},
                                    },
                                    "application/vnd.example+json": {
                                        "schema": {
                                            "type": "array",
                                            "items": {"$ref": "#/components/schemas/User"},
                                        },
                                    },
                                },
                            },
                            "404": {"description": "Not found"},
                        }
                    }
                }
            },
        }

        endpoint = extract_endpoints(spec)[0]

        self.assertEqual(
            endpoint["response_schemas"]["200"]["application/json"]["properties"]["name"]["type"],
            "string",
        )
        self.assertEqual(
            endpoint["response_schemas"]["200"]["application/vnd.example+json"]["items"]["properties"]["name"]["type"],
            "string",
        )
        self.assertNotIn("404", endpoint["response_schemas"])
        self.assertIn("404", endpoint["responses"])

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
