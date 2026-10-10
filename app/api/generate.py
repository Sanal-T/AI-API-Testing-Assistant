import logging

from fastapi import APIRouter, HTTPException

from app.ai.providers import get_llm_provider
from app.generator.ai_generator import (
    AIGenerateRequest,
    generate_ai_test_cases,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/generate/ai")
def generate_custom_ai_tests(request: AIGenerateRequest) -> dict:
    """Generate on-demand AI test cases tailored to an endpoint using multi-model LLMs."""
    if not request.endpoint or not isinstance(request.endpoint, dict):
        raise HTTPException(status_code=400, detail="A valid endpoint definition is required.")

    try:
        provider = get_llm_provider(provider_name=request.provider, model=request.model)
    except ValueError as exc:
        logger.warning("AI test generation requested but provider is not configured: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=f"AI generation unavailable: {exc}. Please configure the relevant API key in your environment.",
        ) from exc

    try:
        test_cases = generate_ai_test_cases(
            endpoint=request.endpoint,
            user_prompt=request.user_prompt,
            count=request.count,
            provider=provider,
        )
    except (RuntimeError, ValueError) as exc:
        logger.exception("AI test generation failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"Failed to generate AI test cases: {exc}",
        ) from exc

    return {
        "message": f"Successfully generated {len(test_cases)} AI test case(s).",
        "total": len(test_cases),
        "test_cases": [test_case.model_dump(mode="json") for test_case in test_cases],
    }
