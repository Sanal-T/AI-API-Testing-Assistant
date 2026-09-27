import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.api.upload import router as upload_router
from app.api.test_runs import router as test_runs_router

log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("app")

app = FastAPI(
    title="AI API Testing Assistant",
    version="1.0.0",
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled server error processing %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred. Please check server logs."},
    )


app.include_router(upload_router)
app.include_router(test_runs_router)


@app.get("/", response_class=HTMLResponse)
def home():
    ui_path = Path(__file__).parent / "ui" / "index.html"
    return ui_path.read_text(encoding="utf-8")
