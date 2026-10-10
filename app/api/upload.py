import json
import logging
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
import yaml

from app.constants import MAX_UPLOAD_SIZE
from app.generator.testcase_generator import generate_test_cases
from app.parser.openapi_parser import (
    OpenAPIError,
    extract_endpoints,
    load_spec_from_string,
    validate_openapi_spec,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Maintained for directory structure backwards compatibility
UPLOAD_DIR = Path("uploads")


@router.post("/upload")
async def upload_spec(file: UploadFile = File(...)):
    contents = await file.read(MAX_UPLOAD_SIZE + 1)
    endpoints = process_spec_upload(file.filename, contents)
    return {
        "message": "Specification parsed successfully.",
        "total_endpoints": len(endpoints),
        "endpoints": endpoints
    }


def process_spec_upload(filename: str | None, contents: bytes) -> list[dict]:
    """Validate and parse bounded upload contents in-memory without persistent disk writes."""
    extension = Path(filename or "").suffix.lower()
    if extension not in {".yaml", ".yml", ".json"}:
        raise HTTPException(
            status_code=400,
            detail="Only .yaml, .yml and .json files are supported.",
        )
    if len(contents) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="Specification file exceeds the 5 MiB upload limit.")
    if not contents:
        raise HTTPException(status_code=400, detail="Specification file is empty.")

    try:
        spec = load_spec_from_string(contents, format_hint=extension)
        validate_openapi_spec(spec)

        endpoints = extract_endpoints(spec)
        for endpoint in endpoints:
            endpoint["test_cases"] = generate_test_cases(endpoint)
    except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError, OpenAPIError) as exc:
        logger.warning("Failed to parse uploaded specification '%s': %s", filename, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info("Successfully parsed specification '%s' with %d endpoints.", filename, len(endpoints))
    return endpoints
