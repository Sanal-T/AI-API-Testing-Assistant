from typing import Any

from pydantic import BaseModel, Field

from app.models.execution_result import TestExecutionResult
from app.models.test_case import TestCase


class VariableExtractor(BaseModel):
    """Rule to capture dynamic values from an HTTP response into the workflow context."""

    source: str = "body"  # 'body' or 'header'
    path: str  # Dot-notation or JSONPath, e.g. 'token', 'data.id', 'access_token'
    variable_name: str  # Context key, e.g. 'auth_token', 'item_id'
    default_value: Any | None = None


class WorkflowStep(BaseModel):
    """An individual step in a chained multi-step scenario."""

    id: str
    name: str
    test_case: TestCase
    extract_variables: list[VariableExtractor] = Field(default_factory=list)
    stop_on_failure: bool = True


class Workflow(BaseModel):
    """An ordered sequence of API operations with state passing and cleanup."""

    name: str
    description: str = ""
    initial_variables: dict[str, Any] = Field(default_factory=dict)
    steps: list[WorkflowStep] = Field(min_length=1)
    teardown_steps: list[WorkflowStep] = Field(default_factory=list)


class WorkflowExecutionResult(BaseModel):
    """Observations and state audit from executing a multi-step workflow."""

    workflow_name: str
    passed: bool
    context_variables: dict[str, Any] = Field(default_factory=dict)
    step_results: list[TestExecutionResult] = Field(default_factory=list)
    teardown_results: list[TestExecutionResult] = Field(default_factory=list)
    duration_ms: float = 0.0
    error: str | None = None


class WorkflowRunRequest(BaseModel):
    """Request payload to execute a workflow."""

    workflow: Workflow
    base_url: str
    allowed_hosts: set[str] = Field(min_length=1)
    request_headers: dict[str, str] = Field(default_factory=dict)
    timeout: float = Field(default=10.0, gt=0, le=60)
    allow_private_network: bool = False
    allow_mutating_methods: bool = True
