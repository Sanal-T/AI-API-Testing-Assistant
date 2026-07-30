from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

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

    return {
        "message": "File uploaded successfully.",
        "filename": file.filename,
        "saved_to": str(file_path)
    }