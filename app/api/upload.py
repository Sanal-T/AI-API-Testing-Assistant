from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from app.parser.openapi_parser import load_spec, extract_endpoints
from app.generator.testcase_generator import (
    generate_valid_payload,
    generate_negative_tests,
    generate_parameter_values
)

router = APIRouter()

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


@router.post("/upload")
async def upload_spec(file: UploadFile = File(...)):
    allowed_extensions = {".yaml", ".yml", ".json"}

    extension = Path(file.filename).suffix.lower()

    if extension not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail="Only .yaml, .yml and .json files are supported."
        )

    file_path = UPLOAD_DIR / file.filename

    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())

    # Parse the uploaded specification
    spec = load_spec(file_path)

    # Extract endpoints
    endpoints = extract_endpoints(spec)
    for endpoint in endpoints:
        schema = endpoint.get("resolved_schema", {})
        parameters = endpoint.get("parameters", [])
        request_body = endpoint.get("request_body", {})
        content = request_body.get("content", {})
        has_request_body_schema = any(
            isinstance(media_type, dict) and "schema" in media_type
            for media_type in content.values()
        )

        endpoint["valid_payload"] = generate_valid_payload(schema)

        endpoint["parameter_values"] = generate_parameter_values(parameters)
        endpoint["negative_tests"] = generate_negative_tests(
            schema,
            include_empty_body_test=has_request_body_schema,
        )
    return {
        "message": "Specification parsed successfully.",
        "total_endpoints": len(endpoints),
        "endpoints": endpoints
    }
