from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from app.api.upload import router as upload_router
from app.api.test_runs import router as test_runs_router

app = FastAPI(
    title="AI API Testing Assistant",
    version="1.0.0"
)

app.include_router(upload_router)
app.include_router(test_runs_router)

@app.get("/", response_class=HTMLResponse)
def home():
    ui_path = Path(__file__).parent / "ui" / "index.html"
    return ui_path.read_text(encoding="utf-8")
