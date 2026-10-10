import json
import logging
from typing import Any
import jsonschema

logger = logging.getLogger(__name__)


class ContractValidationResult:
    """Detailed findings from contract and assertion evaluations."""

    def __init__(
        self,
        is_valid: bool = True,
        schema_passed: bool | None = None,
        schema_errors: list[str] | None = None,
        header_errors: list[str] | None = None,
        assertion_errors: list[str] | None = None,
        sla_exceeded: bool = False,
    ):
        self.is_valid = is_valid
        self.schema_passed = schema_passed
        self.schema_errors = schema_errors or []
        self.header_errors = header_errors or []
        self.assertion_errors = assertion_errors or []
        self.sla_exceeded = sla_exceeded

    @property
    def all_errors(self) -> list[str]:
        errors: list[str] = []
        if self.schema_errors:
            errors.extend([f"Schema drift: {err}" for err in self.schema_errors])
        if self.header_errors:
            errors.extend([f"Header mismatch: {err}" for err in self.header_errors])
        if self.assertion_errors:
            errors.extend([f"Assertion failed: {err}" for err in self.assertion_errors])
        if self.sla_exceeded:
            errors.append("SLA latency threshold exceeded")
        return errors


def validate_response_contract(
    test_case: Any,
    status_code: int | None,
    response_headers: dict[str, str],
    response_body_str: str | None,
    duration_ms: float,
) -> ContractValidationResult:
    """Validate response schema, headers, field assertions, and SLA."""
    schema_errors: list[str] = []
    header_errors: list[str] = []
    assertion_errors: list[str] = []
    schema_passed: bool | None = None
    sla_exceeded = False

    # 1. Latency / SLA validation
    max_duration = getattr(test_case, "max_duration_ms", None)
    if max_duration is not None and duration_ms > max_duration:
        sla_exceeded = True

    # 2. Response Header assertions
    expected_headers = getattr(test_case, "expected_headers", {}) or {}
    lower_actual_headers = {k.lower(): str(v) for k, v in response_headers.items()}
    for exp_header, exp_value in expected_headers.items():
        exp_header_lower = exp_header.lower()
        if exp_header_lower not in lower_actual_headers:
            header_errors.append(f"Missing header '{exp_header}'")
        elif exp_value.lower() not in lower_actual_headers[exp_header_lower].lower():
            header_errors.append(
                f"Header '{exp_header}' expected '{exp_value}', got '{lower_actual_headers[exp_header_lower]}'"
            )

    # 3. JSON Schema Validation
    expected_schema = getattr(test_case, "expected_response_schema", None)
    parsed_json = None
    if expected_schema and response_body_str:
        try:
            parsed_json = json.loads(response_body_str)
            validator = jsonschema.Draft202012Validator(expected_schema)
            raw_errors = list(validator.iter_errors(parsed_json))
            if raw_errors:
                schema_passed = False
                for err in raw_errors[:5]:
                    path = ".".join(str(p) for p in err.absolute_path) or "root"
                    schema_errors.append(f"{path}: {err.message}")
            else:
                schema_passed = True
        except json.JSONDecodeError:
            schema_passed = False
            schema_errors.append("Response body is not valid JSON.")
        except Exception as exc:
            logger.warning("JSON Schema validation error: %s", exc)
            schema_passed = False
            schema_errors.append(f"Validator error: {exc}")

    # 4. JSONPath / Deep Field Assertions
    json_path_assertions = getattr(test_case, "json_path_assertions", []) or []
    if json_path_assertions:
        if parsed_json is None and response_body_str:
            try:
                parsed_json = json.loads(response_body_str)
            except Exception:
                pass

        for assertion in json_path_assertions:
            if not isinstance(assertion, dict):
                continue
            path = assertion.get("path")
            if not path:
                continue

            val = parsed_json
            found = True
            clean_path = str(path).lstrip("$.")
            if clean_path:
                for part in clean_path.split("."):
                    if isinstance(val, dict) and part in val:
                        val = val[part]
                    elif isinstance(val, list) and part.isdigit() and int(part) < len(val):
                        val = val[int(part)]
                    else:
                        found = False
                        break

            if "exists" in assertion and assertion["exists"] != found:
                assertion_errors.append(f"Path '{path}' existence assertion failed.")
            elif not found:
                assertion_errors.append(f"Path '{path}' was not found in response.")
            else:
                if "equals" in assertion and val != assertion["equals"]:
                    assertion_errors.append(f"Path '{path}' expected '{assertion['equals']}', got '{val}'")
                if "contains" in assertion and assertion["contains"] not in str(val):
                    assertion_errors.append(f"Path '{path}' expected to contain '{assertion['contains']}'")
                if "min_count" in assertion and isinstance(val, list) and len(val) < assertion["min_count"]:
                    assertion_errors.append(f"Path '{path}' expected at least {assertion['min_count']} items, got {len(val)}")

    is_valid = (
        (schema_passed is not False)
        and not header_errors
        and not assertion_errors
        and not sla_exceeded
    )

    return ContractValidationResult(
        is_valid=is_valid,
        schema_passed=schema_passed,
        schema_errors=schema_errors,
        header_errors=header_errors,
        assertion_errors=assertion_errors,
        sla_exceeded=sla_exceeded,
    )
