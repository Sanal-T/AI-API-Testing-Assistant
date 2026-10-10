import json
import logging
import os
import re
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

from app.ai.providers import LLMProvider, get_llm_provider
from app.models.test_case import TestCase

logger = logging.getLogger(__name__)


class AIGenerateRequest(BaseModel):
    """Input payload for on-demand AI test case generation."""

    endpoint: dict[str, Any]
    user_prompt: str | None = None
    count: int = Field(default=3, ge=1, le=10)
    provider: str | None = None  # 'openai', 'gemini', 'anthropic', 'local'
    model: str | None = None


class AITestGeneratorProvider(Protocol):
    def generate(self, prompt_data: dict[str, Any]) -> list[dict[str, Any]]: ...


class UnifiedAITestGeneratorAdapter:
    """Adapts any LLMProvider to generate test cases."""

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def generate(self, prompt_data: dict[str, Any]) -> list[dict[str, Any]]:
        system_instruction = (
            "You are an expert AI API Security and Quality Assurance Engineer. "
            "Generate high-value, realistic, and adversarial API test cases for the given endpoint.\n"
            "Include domain-semantic realistic payloads (e.g. realistic names, valid formats, real boundary conditions), "
            "as well as subtle business logic edge cases, parameter tampering, and security boundary tests.\n\n"
            "Return ONLY a valid JSON object with a single key 'test_cases' containing an array of test case objects.\n"
            "Each test case MUST have:\n"
            "- 'name': descriptive name of the test\n"
            "- 'type': 'positive' or 'negative'\n"
            "- 'method': HTTP method\n"
            "- 'path': path template\n"
            "- 'path_params': dict of path params\n"
            "- 'query_params': dict of query params\n"
            "- 'headers': dict of headers\n"
            "- 'body': dict or null\n"
            "- 'expected_status': list of expected HTTP status integers\n"
            "- 'rationale': string explaining why this test is valuable\n"
            "Do NOT include markdown fences. Return raw JSON."
        )
        user_prompt = f"Endpoint contract and testing goals:\n{json.dumps(prompt_data, ensure_ascii=False, indent=2)}"
        output_text = self.llm.complete(system_instruction, user_prompt)
        return _parse_json_test_cases(output_text)


class OpenAITestGeneratorProvider:
    """Standard-library client for generating test cases via OpenAI Responses API."""

    endpoint = "https://api.openai.com/v1/responses"

    def __init__(self, api_key: str, model: str, timeout: float = 35.0):
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for AI test generation.")
        if not model:
            raise ValueError("OPENAI_MODEL is required for AI test generation.")
        if timeout <= 0 or timeout > 60:
            raise ValueError("timeout must be greater than 0 and no more than 60 seconds.")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @classmethod
    def from_environment(cls) -> "OpenAITestGeneratorProvider":
        return cls(
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            model=os.environ.get("OPENAI_MODEL", ""),
        )

    def generate(self, prompt_data: dict[str, Any]) -> list[dict[str, Any]]:
        instructions = (
            "You are an expert AI API Security and Quality Assurance Engineer. "
            "Generate high-value, realistic, and adversarial API test cases for the given endpoint.\n"
            "Return ONLY a valid JSON object with a single key 'test_cases' containing an array of test case objects."
        )

        payload = {
            "model": self.model,
            "instructions": instructions,
            "input": json.dumps(prompt_data, ensure_ascii=False),
            "store": False,
        }

        request = Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                response_data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"OpenAI API returned HTTP {exc.code}.") from None
        except URLError as exc:
            raise RuntimeError("Could not connect to the OpenAI API.") from exc
        except (TimeoutError, OSError) as exc:
            raise RuntimeError("OpenAI API request timed out or network failed.") from exc

        output_text = _extract_output_text(response_data)
        return _parse_json_test_cases(output_text)


def generate_ai_test_cases(
    endpoint: dict[str, Any],
    user_prompt: str | None = None,
    count: int = 3,
    provider: Any | None = None,
    provider_name: str | None = None,
    model: str | None = None,
) -> list[TestCase]:
    """Generate intelligent semantic and edge-case tests using an AI provider."""
    if provider is None:
        try:
            llm = get_llm_provider(provider_name=provider_name, model=model)
            selected_provider = UnifiedAITestGeneratorAdapter(llm)
        except ValueError:
            selected_provider = OpenAITestGeneratorProvider.from_environment()
    elif hasattr(provider, "complete"):
        selected_provider = UnifiedAITestGeneratorAdapter(provider)
    else:
        selected_provider = provider

    prompt_data = _prepare_endpoint_prompt_data(endpoint, user_prompt=user_prompt, count=count)
    raw_cases = selected_provider.generate(prompt_data)

    test_cases: list[TestCase] = []
    default_method = endpoint.get("method", "GET").upper()
    default_path = endpoint.get("path", "/")

    for index, item in enumerate(raw_cases):
        if not isinstance(item, dict):
            continue

        name = item.get("name") or f"AI Test {index + 1}: {default_method} {default_path}"
        test_type = item.get("type", "negative") if item.get("type") in {"positive", "negative"} else "negative"
        method = str(item.get("method") or default_method).upper()
        path = str(item.get("path") or default_path)
        path_params = item.get("path_params") or {}
        query_params = item.get("query_params") or {}
        headers = item.get("headers") or {}
        body = item.get("body")
        expected_status = item.get("expected_status")
        rationale = item.get("rationale")

        if isinstance(expected_status, int):
            expected_status = [expected_status]
        elif not isinstance(expected_status, list):
            expected_status = [200] if test_type == "positive" else [400, 422]

        test_cases.append(
            TestCase(
                name=f"✨ {name}",
                method=method,
                path=path,
                type=test_type,
                path_params=path_params,
                query_params=query_params,
                headers=headers,
                body=body,
                expected_status=expected_status,
                rationale=rationale,
            )
        )

    return test_cases


def _parse_json_test_cases(output_text: str) -> list[dict[str, Any]]:
    try:
        cleaned_text = re.sub(r"^```(?:json)?\s*", "", output_text.strip(), flags=re.MULTILINE)
        cleaned_text = re.sub(r"```$", "", cleaned_text.strip(), flags=re.MULTILINE)
        parsed = json.loads(cleaned_text)
        if isinstance(parsed, dict) and "test_cases" in parsed and isinstance(parsed["test_cases"], list):
            return parsed["test_cases"]
        if isinstance(parsed, list):
            return parsed
        raise ValueError("AI response did not contain a 'test_cases' list.")
    except (TypeError, json.JSONDecodeError) as exc:
        logger.error("Failed to parse JSON response from AI provider: %s", output_text)
        raise ValueError("AI provider returned invalid JSON test cases.") from exc


def _prepare_endpoint_prompt_data(
    endpoint: dict[str, Any],
    user_prompt: str | None = None,
    count: int = 3,
) -> dict[str, Any]:
    return {
        "method": endpoint.get("method", "GET"),
        "path": endpoint.get("path", "/"),
        "summary": endpoint.get("summary", ""),
        "description": endpoint.get("description", ""),
        "parameters": [
            {
                "name": param.get("name"),
                "location": param.get("location"),
                "required": param.get("required"),
                "schema": param.get("schema"),
            }
            for param in endpoint.get("parameters", [])
            if isinstance(param, dict)
        ],
        "request_body_schema": endpoint.get("resolved_schema", {}),
        "request_body_required": endpoint.get("request_body_required", False),
        "response_status_codes": list(endpoint.get("responses", {}).keys()),
        "user_goal": user_prompt or "Generate semantic domain tests and subtle edge cases.",
        "target_test_count": count,
    }


def _extract_output_text(response: dict[str, Any]) -> str:
    chunks: list[str] = []
    for item in response.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text":
                text = content.get("text")
                if isinstance(text, str):
                    chunks.append(text)
    if not chunks:
        raise ValueError("AI provider response did not contain text output.")
    return "\n".join(chunks)
