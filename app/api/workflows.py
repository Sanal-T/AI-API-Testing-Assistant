import logging
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.executor.workflow_runner import execute_workflow
from app.generator.workflow_generator import generate_crud_workflows
from app.models.workflow import WorkflowRunRequest

logger = logging.getLogger(__name__)

router = APIRouter()


class WorkflowGenerateRequest(BaseModel):
    endpoints: list[dict]


@router.post("/workflows/generate")
def generate_workflows_endpoint(request: WorkflowGenerateRequest) -> dict:
    """Analyze endpoints and generate multi-step lifecycle scenarios with variable chaining."""
    if not request.endpoints:
        raise HTTPException(status_code=400, detail="Endpoints list cannot be empty.")

    workflows = generate_crud_workflows(request.endpoints)
    return {
        "message": f"Generated {len(workflows)} multi-step workflow(s).",
        "total": len(workflows),
        "workflows": [w.model_dump(mode="json") for w in workflows],
    }


@router.post("/workflows/run")
def run_workflow_endpoint(request: WorkflowRunRequest) -> dict:
    """Execute a multi-step API workflow with dynamic context passing and cleanup."""
    _validate_workflow_run_target(request)

    try:
        result = execute_workflow(
            workflow=request.workflow,
            base_url=request.base_url,
            allowed_hosts=request.allowed_hosts,
            request_headers=request.request_headers,
            timeout=request.timeout,
            allow_private_network=request.allow_private_network,
            allow_mutating_methods=request.allow_mutating_methods,
        )
    except Exception as exc:
        logger.exception("Workflow execution crashed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Workflow run failed: {exc}") from exc

    return {
        "workflow_name": result.workflow_name,
        "passed": result.passed,
        "duration_ms": result.duration_ms,
        "context_variables": result.context_variables,
        "error": result.error,
        "step_results": [
            {
                "name": r.test_case.name,
                "method": r.test_case.method,
                "path": r.test_case.path,
                "outcome": r.outcome.value,
                "actual_status": r.actual_status,
                "duration_ms": r.duration_ms,
                "error": r.error,
                "schema_validation_passed": r.schema_validation_passed,
                "schema_validation_errors": r.schema_validation_errors,
                "assertion_errors": r.assertion_errors,
                "sla_exceeded": r.sla_exceeded,
            }
            for r in result.step_results
        ],
        "teardown_results": [
            {
                "name": r.test_case.name,
                "method": r.test_case.method,
                "path": r.test_case.path,
                "outcome": r.outcome.value,
                "actual_status": r.actual_status,
                "duration_ms": r.duration_ms,
                "error": r.error,
            }
            for r in result.teardown_results
        ],
    }


def _validate_workflow_run_target(request: WorkflowRunRequest) -> None:
    parsed = urlsplit(request.base_url)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise HTTPException(status_code=400, detail="base_url must be an absolute HTTP(S) URL.")

    normalized_host = parsed.hostname.rstrip(".").lower()
    allowed_hosts = {host.strip("[]").rstrip(".").lower() for host in request.allowed_hosts}
    if normalized_host not in allowed_hosts:
        raise HTTPException(status_code=400, detail="base_url hostname must be in allowed_hosts.")
