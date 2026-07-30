from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.parser.openapi_parser import load_spec, extract_endpoints

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

    return {
        "message": "Specification parsed successfully.",
        "total_endpoints": len(endpoints),
        "endpoints": endpoints
    }