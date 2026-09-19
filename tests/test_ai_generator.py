import json
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.api.generate import generate_custom_ai_tests
from app.generator.ai_generator import (
    AIGenerateRequest,
    OpenAITestGeneratorProvider,
    generate_ai_test_cases,
)
from app.models.test_case import TestCase


class _FakeAIGeneratorProvider:
    def __init__(self, cases: list[dict] | None = None):
        self.received_prompt_data = None
        self.cases = cases or [
            {
                "name": "SQL injection attempt in query param",
                "type": "negative",
                "method": "GET",
                "path": "/users",
                "path_params": {},
                "query_params": {"search": "' OR 1=1 --"},
                "headers": {},
                "body": None,
                "expected_status": [400, 422],
                "rationale": "Verifies that unsanitized SQL injection payloads are rejected.",
            },
            {
                "name": "Valid semantic user profile payload",
                "type": "positive",
                "method": "POST",
                "path": "/users",
                "path_params": {},
                "query_params": {},
                "headers": {},
                "body": {"username": "alice_smith", "email": "alice@domain.org"},
                "expected_status": [201],
                "rationale": "Tests a realistic semantic user creation payload.",
            },
        ]

    def generate(self, prompt_data: dict) -> list[dict]:
        self.received_prompt_data = prompt_data
        return self.cases


class AITestGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.endpoint = {
            "method": "POST",
            "path": "/users",
            "summary": "Create user",
            "description": "Registers a new user",
            "parameters": [
                {"name": "org_id", "location": "query", "required": False, "schema": {"type": "string"}}
            ],
            "resolved_schema": {
                "type": "object",
                "properties": {
                    "username": {"type": "string"},
                    "email": {"type": "string", "format": "email"},
                },
                "required": ["username", "email"],
            },
            "responses": {"201": {"description": "created"}, "400": {"description": "bad request"}},
        }

    def test_generate_ai_test_cases_transforms_raw_cases_to_test_case_models(self):
        provider = _FakeAIGeneratorProvider()
        test_cases = generate_ai_test_cases(
            endpoint=self.endpoint,
            user_prompt="Focus on SQL injection and realistic user data",
            count=2,
            provider=provider,
        )

        self.assertEqual(len(test_cases), 2)
        self.assertIsInstance(test_cases[0], TestCase)
        self.assertIn("SQL injection", test_cases[0].name)
        self.assertEqual(test_cases[0].type, "negative")
        self.assertEqual(test_cases[0].expected_status, [400, 422])
        self.assertIn("unsanitized SQL", test_cases[0].rationale)

        self.assertIsInstance(test_cases[1], TestCase)
        self.assertEqual(test_cases[1].type, "positive")
        self.assertEqual(test_cases[1].body["username"], "alice_smith")
        self.assertEqual(test_cases[1].expected_status, [201])

        # Verify prompt data structure passed to provider
        self.assertEqual(provider.received_prompt_data["method"], "POST")
        self.assertEqual(provider.received_prompt_data["path"], "/users")
        self.assertEqual(provider.received_prompt_data["target_test_count"], 2)
        self.assertIn("SQL injection", provider.received_prompt_data["user_goal"])

    def test_provider_raises_value_error_when_api_key_missing(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "", "OPENAI_MODEL": ""}):
            with self.assertRaises(ValueError):
                OpenAITestGeneratorProvider.from_environment()

    def test_provider_parses_json_output_with_markdown_fences(self):
        provider = OpenAITestGeneratorProvider("dummy-key", "gpt-4o-mini")
        raw_response = {
            "output": [{
                "type": "message",
                "content": [{
                    "type": "output_text",
                    "text": '```json\n{"test_cases": [{"name": "Fenced test", "type": "positive", "method": "GET", "path": "/test"}]}\n```',
                }],
            }]
        }

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(raw_response).encode("utf-8")
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            cases = provider.generate({"dummy": "data"})
            self.assertEqual(len(cases), 1)
            self.assertEqual(cases[0]["name"], "Fenced test")

    def test_api_generate_endpoint_requires_configured_provider(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            with self.assertRaises(HTTPException) as raised:
                generate_custom_ai_tests(
                    AIGenerateRequest(endpoint=self.endpoint, user_prompt="Test something")
                )
            self.assertEqual(raised.exception.status_code, 503)

    def test_api_generate_endpoint_returns_json_serialized_cases(self):
        provider = _FakeAIGeneratorProvider()
        with (
            patch("app.api.generate.OpenAITestGeneratorProvider.from_environment", return_value=provider),
            patch("app.api.generate.generate_ai_test_cases", return_value=[
                TestCase(
                    name="AI Custom Test",
                    method="GET",
                    path="/users",
                    type="negative",
                    expected_status=[400],
                    rationale="Testing edge condition",
                )
            ]),
        ):
            response = generate_custom_ai_tests(
                AIGenerateRequest(endpoint=self.endpoint, user_prompt="test", count=1)
            )
            self.assertEqual(response["total"], 1)
            self.assertEqual(len(response["test_cases"]), 1)
            self.assertEqual(response["test_cases"][0]["name"], "AI Custom Test")
            self.assertEqual(response["test_cases"][0]["rationale"], "Testing edge condition")


if __name__ == "__main__":
    unittest.main()
