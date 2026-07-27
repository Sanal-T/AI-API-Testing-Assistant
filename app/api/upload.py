from fastapi import APIRouter, UploadFile, File

router = APIRouter()

@router.post("/upload")
async def upload_spec(file: UploadFile = File(...)):
    return {
        "filename": file.filename,
        "content_type": file.content_type
    }