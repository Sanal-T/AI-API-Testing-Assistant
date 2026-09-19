import copy
import json
import logging
import re
from time import perf_counter
from typing import Any

from app.executor.http_executor import execute_test_case
from app.models.execution_result import ExecutionOutcome, TestExecutionResult
from app.models.test_case import TestCase
from app.models.workflow import (
    VariableExtractor,
    Workflow,
    WorkflowExecutionResult,
    WorkflowStep,
)

logger = logging.getLogger(__name__)

_TEMPLATE_REGEX = re.compile(r"\{\{([a-zA-Z0-9_\-]+)\}\}")


def resolve_placeholders(data: Any, context: dict[str, Any]) -> Any:
    """Recursively replace {{variable_name}} templates with values from context."""
    if isinstance(data, str):
        # Exact match single token (preserves native types like int, bool, dict)
        exact_match = _TEMPLATE_REGEX.fullmatch(data.strip())
        if exact_match:
            var_name = exact_match.group(1)
            if var_name in context:
                return context[var_name]

        def replace_fn(match: re.Match) -> str:
            var_name = match.group(1)
            return str(context.get(var_name, match.group(0)))

        return _TEMPLATE_REGEX.sub(replace_fn, data)

    if isinstance(data, dict):
        return {
            resolve_placeholders(k, context): resolve_placeholders(v, context)
            for k, v in data.items()
        }

    if isinstance(data, list):
        return [resolve_placeholders(item, context) for item in data]

    return data


def extract_variable_from_response(
    extractor: VariableExtractor,
    result: TestExecutionResult,
) -> Any:
    """Extract a value from response body or response headers using dot-notation."""
    if extractor.source == "header":
        lower_headers = {k.lower(): v for k, v in result.response_headers.items()}
        return lower_headers.get(extractor.path.lower(), extractor.default_value)

    # Source is body
    if not result.response_body:
        return extractor.default_value

    try:
        parsed = json.loads(result.response_body)
    except Exception:
        return extractor.default_value

    clean_path = extractor.path.lstrip("$.")
    if not clean_path:
        return parsed

    val = parsed
    for part in clean_path.split("."):
        if isinstance(val, dict) and part in val:
            val = val[part]
        elif isinstance(val, list) and part.isdigit() and int(part) < len(val):
            val = val[int(part)]
        else:
            return extractor.default_value

    return val


def execute_workflow(
    workflow: Workflow,
    base_url: str,
    *,
    allowed_hosts: set[str],
    request_headers: dict[str, str] | None = None,
    timeout: float = 10.0,
    allow_private_network: bool = False,
    allow_mutating_methods: bool = True,
) -> WorkflowExecutionResult:
    """Execute an ordered multi-step API workflow with dynamic context passing and teardown."""
    context: dict[str, Any] = copy.deepcopy(workflow.initial_variables)
    global_headers = request_headers or {}
    step_results: list[TestExecutionResult] = []
    teardown_results: list[TestExecutionResult] = []
    workflow_passed = True
    workflow_error: str | None = None
    started = perf_counter()

    # 1. Execute Main Sequential Steps
    for step in workflow.steps:
        resolved_case = _prepare_resolved_test_case(step.test_case, context, global_headers)
        try:
            result = execute_test_case(
                resolved_case,
                base_url,
                allowed_hosts=allowed_hosts,
                timeout=timeout,
                allow_private_network=allow_private_network,
                allow_mutating_methods=allow_mutating_methods,
            )
        except Exception as exc:
            logger.exception("Step '%s' failed unexpectedly: %s", step.name, exc)
            result = TestExecutionResult(
                test_case=resolved_case,
                outcome=ExecutionOutcome.ERROR,
                duration_ms=0,
                error=f"Execution error: {exc}",
            )

        step_results.append(result)

        # Extract variables if step succeeded (or outcome is PASSED/UNVERIFIED)
        for extractor in step.extract_variables:
            extracted_val = extract_variable_from_response(extractor, result)
            if extracted_val is not None:
                context[extractor.variable_name] = extracted_val
                logger.info("Workflow context extracted: %s = %r", extractor.variable_name, extracted_val)

        if result.outcome not in {ExecutionOutcome.PASSED, ExecutionOutcome.UNVERIFIED}:
            workflow_passed = False
            workflow_error = f"Step '{step.name}' failed with outcome '{result.outcome.value}': {result.error}"
            if step.stop_on_failure:
                logger.warning("Stopping workflow '%s' due to failure in step '%s'", workflow.name, step.name)
                break

    # 2. Execute Teardown / Cleanup Steps (always run to prevent dangling test resources)
    for teardown_step in workflow.teardown_steps:
        resolved_teardown = _prepare_resolved_test_case(teardown_step.test_case, context, global_headers)
        try:
            td_result = execute_test_case(
                resolved_teardown,
                base_url,
                allowed_hosts=allowed_hosts,
                timeout=timeout,
                allow_private_network=allow_private_network,
                allow_mutating_methods=allow_mutating_methods,
            )
        except Exception as exc:
            logger.warning("Teardown step '%s' failed: %s", teardown_step.name, exc)
            td_result = TestExecutionResult(
                test_case=resolved_teardown,
                outcome=ExecutionOutcome.ERROR,
                duration_ms=0,
                error=f"Teardown error: {exc}",
            )
        teardown_results.append(td_result)

    total_duration_ms = (perf_counter() - started) * 1000

    return WorkflowExecutionResult(
        workflow_name=workflow.name,
        passed=workflow_passed,
        context_variables=context,
        step_results=step_results,
        teardown_results=teardown_results,
        duration_ms=total_duration_ms,
        error=workflow_error,
    )


def _prepare_resolved_test_case(
    case: TestCase,
    context: dict[str, Any],
    global_headers: dict[str, str],
) -> TestCase:
    """Clone a TestCase and inject resolved context variables into all parameters and payloads."""
    headers = {**global_headers, **case.headers}

    resolved_path = resolve_placeholders(case.path, context)
    resolved_path_params = resolve_placeholders(case.path_params, context)
    resolved_query_params = resolve_placeholders(case.query_params, context)
    resolved_headers = resolve_placeholders(headers, context)
    resolved_body = resolve_placeholders(case.body, context) if case.body is not None else None

    return case.model_copy(
        update={
            "path": resolved_path,
            "path_params": resolved_path_params,
            "query_params": resolved_query_params,
            "headers": resolved_headers,
            "body": resolved_body,
        }
    )
