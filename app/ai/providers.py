import json
import logging
import os
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


class LLMProvider(Protocol):
    """Protocol for unified multi-model LLM generation."""

    def complete(self, system_instruction: str, user_prompt: str) -> str:
        """Execute completion and return raw text response."""
        ...


class OpenAIProvider:
    """Provider for OpenAI models and OpenAI-compatible endpoints."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 35.0,
    ):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.timeout = timeout

        if not self.api_key and not os.environ.get("LOCAL_LLM_URL"):
            raise ValueError("OPENAI_API_KEY is required for OpenAI provider.")

    def complete(self, system_instruction: str, user_prompt: str) -> str:
        endpoint = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        response_data = _http_post_json(endpoint, payload, headers, timeout=self.timeout)
        try:
            return response_data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise ValueError(f"Unexpected response structure from OpenAI: {response_data}") from exc


class GeminiProvider:
    """Provider for Google Gemini models via Google Generative Language API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 35.0,
    ):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
        self.timeout = timeout

        if not self.api_key:
            raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY is required for Gemini provider.")

    def complete(self, system_instruction: str, user_prompt: str) -> str:
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        payload = {
            "system_instruction": {
                "parts": [{"text": system_instruction}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
            },
        }
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        response_data = _http_post_json(endpoint, payload, headers, timeout=self.timeout)
        try:
            return response_data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise ValueError(f"Unexpected response structure from Gemini: {response_data}") from exc


class AnthropicProvider:
    """Provider for Anthropic Claude models via Messages API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 35.0,
    ):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
        self.timeout = timeout

        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for Anthropic provider.")

    def complete(self, system_instruction: str, user_prompt: str) -> str:
        endpoint = "https://api.anthropic.com/v1/messages"
        payload = {
            "model": self.model,
            "system": system_instruction,
            "messages": [
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": 4096,
            "temperature": 0.2,
        }
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

        response_data = _http_post_json(endpoint, payload, headers, timeout=self.timeout)
        try:
            return response_data["content"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise ValueError(f"Unexpected response structure from Anthropic: {response_data}") from exc


class LocalOllamaProvider:
    """Provider for Local models (Ollama, vLLM, LM Studio, LocalAI) without cloud dependencies."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 45.0,
    ):
        self.base_url = (base_url or os.environ.get("LOCAL_LLM_URL", "http://localhost:11434/v1")).rstrip("/")
        self.model = model or os.environ.get("LOCAL_LLM_MODEL", "llama3")
        self.timeout = timeout

    def complete(self, system_instruction: str, user_prompt: str) -> str:
        endpoint = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        headers = {
            "Content-Type": "application/json",
        }

        response_data = _http_post_json(endpoint, payload, headers, timeout=self.timeout)
        try:
            return response_data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise ValueError(f"Unexpected response structure from Local LLM: {response_data}") from exc


def get_llm_provider(
    provider_name: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> LLMProvider:
    """Factory creating the appropriate LLM provider with auto-detection."""
    requested = (provider_name or os.environ.get("AI_PROVIDER", "auto")).lower()

    if requested == "gemini" or (requested == "auto" and (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))):
        return GeminiProvider(api_key=api_key, model=model)

    if requested == "anthropic" or (requested == "auto" and os.environ.get("ANTHROPIC_API_KEY")):
        return AnthropicProvider(api_key=api_key, model=model)

    if requested in {"local", "ollama", "vllm"} or (requested == "auto" and os.environ.get("LOCAL_LLM_URL")):
        return LocalOllamaProvider(base_url=base_url, model=model)

    # Default to OpenAI
    return OpenAIProvider(api_key=api_key, model=model, base_url=base_url)


def _http_post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: float = 35.0,
) -> dict[str, Any]:
    """Helper sending an HTTP POST request and returning parsed JSON."""
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers=headers, method="POST")

    try:
        with urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
        raise RuntimeError(f"AI Provider returned HTTP {exc.code}: {err_body}") from None
    except URLError as exc:
        raise RuntimeError(f"Network error connecting to AI provider at {url}: {exc.reason}") from exc
    except (TimeoutError, OSError) as exc:
        raise RuntimeError(f"Connection to AI provider timed out: {exc}") from exc
