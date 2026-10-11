import logging
import os
import hmac
import ipaddress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from dotenv import load_dotenv

load_dotenv()

from app.api.upload import router as upload_router
from app.api.test_runs import router as test_runs_router
from app.api.generate import router as generate_router
from app.api.workflows import router as workflows_router
from app.api.export import router as export_router

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


@app.middleware("http")
async def protect_api(request: Request, call_next):
    """Require a configured bearer token off-loopback; honor it when configured."""
    if request.url.path in {"/", "/docs", "/redoc", "/openapi.json"}:
        return await call_next(request)

    configured_token = os.environ.get("API_ACCESS_TOKEN", "").strip()
    authorization = request.headers.get("authorization", "")
    supplied_token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    if configured_token:
        if not supplied_token or not hmac.compare_digest(supplied_token, configured_token):
            return JSONResponse(status_code=401, content={"detail": "A valid API bearer token is required."})
    else:
        peer = request.client.host if request.client else ""
        try:
            is_loopback = ipaddress.ip_address(peer).is_loopback
        except ValueError:
            is_loopback = False
        if not is_loopback:
            return JSONResponse(
                status_code=403,
                content={"detail": "Remote API access is disabled until API_ACCESS_TOKEN is configured."},
            )
    return await call_next(request)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled server error processing %s %s: %s",
        request.method,
        request.url.path,
        exc,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred. Please check server logs."},
    )


app.include_router(upload_router)
app.include_router(test_runs_router)
app.include_router(generate_router)
app.include_router(workflows_router)
app.include_router(export_router)


@app.get("/", response_class=HTMLResponse)
def home():
    ui_path = Path(__file__).parent / "ui" / "index.html"
    return ui_path.read_text(encoding="utf-8")
