from collections import Counter
from collections.abc import Iterable

from app.models.execution_result import ExecutionOutcome, TestExecutionResult


_OUTCOME_NAMES = [outcome.value for outcome in ExecutionOutcome]


def build_execution_report(results: Iterable[TestExecutionResult]) -> dict:
    """Build a JSON-safe, credential-conscious summary of execution results.

    Pass rate is passed / (passed + failed), so tests with no evaluated status
    assertion and skipped tests do not distort the assertion pass rate.
    """
    endpoint_groups = {}
    type_counts = {}
    outcome_counts = Counter()
    contract_violations_count = 0
    sla_violations_count = 0
    total = 0

    for result in results:
        total += 1
        outcome = result.outcome.value
        outcome_counts[outcome] += 1

        has_contract_violation = bool(
            result.schema_validation_passed is False
            or result.schema_validation_errors
            or result.header_validation_errors
            or result.assertion_errors
        )
        if has_contract_violation:
            contract_violations_count += 1
        if result.sla_exceeded:
            sla_violations_count += 1

        test_case = result.test_case
        endpoint_key = (test_case.method.upper(), test_case.path)
        endpoint = endpoint_groups.setdefault(endpoint_key, {
            "method": endpoint_key[0],
            "path": endpoint_key[1],
            "counts": Counter(),
            "results": [],
        })
        endpoint["counts"][outcome] += 1

        test_type = test_case.type
        type_counts.setdefault(test_type, Counter())[outcome] += 1
        endpoint["results"].append({
            "name": test_case.name,
            "type": test_type,
            "outcome": outcome,
            "expected_status": test_case.expected_status,
            "actual_status": result.actual_status,
            "duration_ms": result.duration_ms,
            "error_kind": result.error_kind.value if result.error_kind else None,
            "error": result.error,
            "schema_validation_passed": result.schema_validation_passed,
            "schema_validation_errors": result.schema_validation_errors,
            "header_validation_errors": result.header_validation_errors,
            "assertion_errors": result.assertion_errors,
            "sla_exceeded": result.sla_exceeded,
        })

    passed = outcome_counts[ExecutionOutcome.PASSED.value]
    failed = outcome_counts[ExecutionOutcome.FAILED.value]
    evaluated = passed + failed
    counts = {name: outcome_counts[name] for name in _OUTCOME_NAMES}

    return {
        "summary": {
            "total_tests": total,
            "executed_tests": total - outcome_counts[ExecutionOutcome.SKIPPED.value],
            "assertions_evaluated": evaluated,
            "counts": counts,
            "pass_rate": round(passed / evaluated, 4) if evaluated else None,
            "contract_violations": contract_violations_count,
            "sla_violations": sla_violations_count,
        },
        "by_endpoint": [
            {
                "method": endpoint["method"],
                "path": endpoint["path"],
                "counts": _complete_counts(endpoint["counts"]),
                "results": endpoint["results"],
            }
            for endpoint in endpoint_groups.values()
        ],
        "by_test_type": {
            test_type: _complete_counts(counts_by_outcome)
            for test_type, counts_by_outcome in type_counts.items()
        },
    }


def _complete_counts(counts: Counter) -> dict[str, int]:
    return {name: counts[name] for name in _OUTCOME_NAMES}
