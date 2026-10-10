import json
import unittest
from unittest.mock import MagicMock, patch

from app.ai.providers import (
    AnthropicProvider,
    GeminiProvider,
    LocalOllamaProvider,
    OpenAIProvider,
    get_llm_provider,
)
from app.analysis.failure_analyzer import analyze_failures
from app.generator.ai_generator import generate_ai_test_cases
from app.models.execution_result import ExecutionOutcome, TestExecutionResult
from app.models.test_case import TestCase


class _MockLLM:
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.system = None
        self.prompt = None

    def complete(self, system_instruction: str, user_prompt: str) -> str:
        self.system = system_instruction
        self.prompt = user_prompt
        return self.response_text


class MultiModelProviderTests(unittest.TestCase):
    def test_factory_selects_correct_provider_based_on_environment(self):
        # Gemini auto-detection
        with patch.dict("os.environ", {"GEMINI_API_KEY": "gemini-key", "OPENAI_API_KEY": ""}):
            prov = get_llm_provider()
            self.assertIsInstance(prov, GeminiProvider)

        # Anthropic auto-detection
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "claude-key", "GEMINI_API_KEY": "", "OPENAI_API_KEY": ""}):
            prov = get_llm_provider()
            self.assertIsInstance(prov, AnthropicProvider)

        # Local Ollama selection
        with patch.dict("os.environ", {"AI_PROVIDER": "local"}):
            prov = get_llm_provider()
            self.assertIsInstance(prov, LocalOllamaProvider)

        # Default OpenAI selection
        with patch.dict("os.environ", {"OPENAI_API_KEY": "openai-key", "AI_PROVIDER": "openai"}):
            prov = get_llm_provider()
            self.assertIsInstance(prov, OpenAIProvider)

    def test_gemini_provider_parses_response_payload(self):
        provider = GeminiProvider(api_key="test-key", model="gemini-2.0-flash")
        fake_gemini_response = {
            "candidates": [{
                "content": {
                    "parts": [{"text": "Hello from Gemini"}]
                }
            }]
        }

        with patch("app.ai.providers._http_post_json", return_value=fake_gemini_response) as mock_post:
            output = provider.complete("system rules", "user question")
            self.assertEqual(output, "Hello from Gemini")
            self.assertEqual(mock_post.call_args[0][2]["x-goog-api-key"], "test-key")

    def test_anthropic_provider_parses_response_payload(self):
        provider = AnthropicProvider(api_key="test-key", model="claude-3-5-sonnet-20241022")
        fake_claude_response = {
            "content": [{"text": "Hello from Claude"}]
        }

        with patch("app.ai.providers._http_post_json", return_value=fake_claude_response) as mock_post:
            output = provider.complete("system rules", "user question")
            self.assertEqual(output, "Hello from Claude")
            self.assertEqual(mock_post.call_args[0][2]["x-api-key"], "test-key")

    def test_local_ollama_provider_requires_no_cloud_keys(self):
        provider = LocalOllamaProvider(base_url="http://localhost:11434/v1", model="llama3")
        fake_ollama_response = {
            "choices": [{
                "message": {"content": "Hello from Local Llama"}
            }]
        }

        with patch("app.ai.providers._http_post_json", return_value=fake_ollama_response):
            output = provider.complete("system rules", "user question")
            self.assertEqual(output, "Hello from Local Llama")

    def test_analyze_failures_works_seamlessly_with_any_llm_provider(self):
        mock_llm = _MockLLM(
            json.dumps({
                "summary": "Multi-model diagnosis",
                "observed_facts": ["Endpoint 500 error"],
                "hypotheses": ["Database timeout"],
                "recommendations": ["Scale DB pool"],
            })
        )

        test_case = TestCase(name="Check Status", method="GET", path="/status", type="positive")
        failed_result = TestExecutionResult(
            test_case=test_case,
            outcome=ExecutionOutcome.FAILED,
            actual_status=500,
            duration_ms=100.0,
        )

        analysis = analyze_failures([failed_result], provider=mock_llm)
        self.assertEqual(analysis.summary, "Multi-model diagnosis")
        self.assertEqual(analysis.hypotheses, ["Database timeout"])

    def test_generate_ai_test_cases_works_seamlessly_with_any_llm_provider(self):
        mock_llm = _MockLLM(
            json.dumps({
                "test_cases": [
                    {
                        "name": "Gemini Edge Case",
                        "type": "negative",
                        "method": "POST",
                        "path": "/orders",
                        "expected_status": [400],
                        "rationale": "Generated via Gemini provider",
                    }
                ]
            })
        )

        endpoint = {"method": "POST", "path": "/orders", "responses": {"201": {}}}
        cases = generate_ai_test_cases(endpoint, count=1, provider=mock_llm)
        self.assertEqual(len(cases), 1)
        self.assertIn("Gemini Edge Case", cases[0].name)
        self.assertEqual(cases[0].rationale, "Generated via Gemini provider")


if __name__ == "__main__":
    unittest.main()
