from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile
import yaml

from app.parser.openapi_parser import load_spec, extract_endpoints, validate_openapi_spec
from app.generator.testcase_generator import generate_test_cases
from openapi_spec_validator.exceptions import OpenAPIError

router = APIRouter()

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
MAX_UPLOAD_SIZE = 5 * 1024 * 1024


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
    """Persist, validate, and parse bounded upload contents safely."""
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

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_path = UPLOAD_DIR / f"{uuid4().hex}{extension}"
    file_path.write_bytes(contents)

    try:
        spec = load_spec(file_path)
        validate_openapi_spec(spec)

        endpoints = extract_endpoints(spec)
        for endpoint in endpoints:
            endpoint["test_cases"] = generate_test_cases(endpoint)
    except (OSError, ValueError, yaml.YAMLError, OpenAPIError) as exc:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return endpoints
