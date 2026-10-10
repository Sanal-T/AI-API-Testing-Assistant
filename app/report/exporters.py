import json
import re
from collections import defaultdict
from collections.abc import Sequence
from xml.etree import ElementTree

from app.models.execution_result import ExecutionOutcome, TestExecutionResult
from app.models.test_case import TestCase


def export_to_junit_xml(
    results: Sequence[TestExecutionResult],
    suite_name: str = "API Test Assistant",
) -> str:
    """Export test execution results to standard JUnit XML format."""
    total_tests = len(results)
    failures = sum(1 for r in results if r.outcome == ExecutionOutcome.FAILED)
    errors = sum(1 for r in results if r.outcome == ExecutionOutcome.ERROR)
    skipped = sum(1 for r in results if r.outcome == ExecutionOutcome.SKIPPED)
    total_time_sec = sum(r.duration_ms for r in results) / 1000.0

    root = ElementTree.Element(
        "testsuites",
        name=suite_name,
        tests=str(total_tests),
        failures=str(failures),
        errors=str(errors),
        skipped=str(skipped),
        time=f"{total_time_sec:.3f}",
    )

    by_endpoint: dict[str, list[TestExecutionResult]] = defaultdict(list)
    for res in results:
        endpoint_key = f"{res.test_case.method.upper()} {res.test_case.path}"
        by_endpoint[endpoint_key].append(res)

    for endpoint_name, group in by_endpoint.items():
        ep_failures = sum(1 for r in group if r.outcome == ExecutionOutcome.FAILED)
        ep_errors = sum(1 for r in group if r.outcome == ExecutionOutcome.ERROR)
        ep_skipped = sum(1 for r in group if r.outcome == ExecutionOutcome.SKIPPED)
        ep_time_sec = sum(r.duration_ms for r in group) / 1000.0

        suite = ElementTree.SubElement(
            root,
            "testsuite",
            name=endpoint_name,
            tests=str(len(group)),
            failures=str(ep_failures),
            errors=str(ep_errors),
            skipped=str(ep_skipped),
            time=f"{ep_time_sec:.3f}",
        )

        for res in group:
            tc = res.test_case
            testcase_elem = ElementTree.SubElement(
                suite,
                "testcase",
                name=tc.name,
                classname=f"{tc.method.upper()} {tc.path}",
                time=f"{(res.duration_ms / 1000.0):.3f}",
            )

            if res.outcome == ExecutionOutcome.FAILED:
                fail_elem = ElementTree.SubElement(
                    testcase_elem,
                    "failure",
                    message=res.error or "Assertion failed",
                    type="AssertionError",
                )
                fail_elem.text = res.error or "Assertion failed"
            elif res.outcome == ExecutionOutcome.ERROR:
                err_elem = ElementTree.SubElement(
                    testcase_elem,
                    "error",
                    message=res.error or "Execution error",
                    type=res.error_kind.value if res.error_kind else "ExecutionError",
                )
                err_elem.text = res.error or "Execution error"
            elif res.outcome == ExecutionOutcome.SKIPPED:
                ElementTree.SubElement(testcase_elem, "skipped", message="Skipped")

    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


def export_to_postman_collection(
    test_cases: Sequence[TestCase],
    collection_name: str = "API Test Assistant Collection",
    base_url_var: str = "{{baseUrl}}",
) -> dict:
    """Export test cases directly to Postman Collection v2.1 format."""
    endpoints_map: dict[str, list[TestCase]] = defaultdict(list)
    for tc in test_cases:
        endpoints_map[f"{tc.method.upper()} {tc.path}"].append(tc)

    items = []
    for endpoint_name, cases in endpoints_map.items():
        folder_items = []
        for tc in cases:
            headers = [
                {"key": k, "value": str(v), "type": "text"}
                for k, v in tc.headers.items()
            ]

            url_path = [segment for segment in tc.path.strip("/").split("/") if segment]
            query_params = [
                {"key": k, "value": str(v)}
                for k, v in tc.query_params.items()
            ]

            request_obj: dict = {
                "method": tc.method.upper(),
                "header": headers,
                "url": {
                    "raw": f"{base_url_var}{tc.path}",
                    "host": [base_url_var],
                    "path": url_path,
                },
            }
            if query_params:
                request_obj["url"]["query"] = query_params

            if tc.body is not None:
                headers.append({"key": "Content-Type", "value": "application/json", "type": "text"})
                request_obj["body"] = {
                    "mode": "raw",
                    "raw": json.dumps(tc.body, indent=2),
                    "options": {"raw": {"language": "json"}},
                }

            expected = tc.expected_status or [200]
            expected_json = json.dumps(expected)
            test_script = [
                "pm.test(\"Status code is one of expected: " + expected_json + "\", function () {",
                f"    pm.expect({expected_json}).to.include(pm.response.code);",
                "});",
            ]

            folder_items.append({
                "name": tc.name,
                "request": request_obj,
                "event": [
                    {
                        "listen": "test",
                        "script": {
                            "type": "text/javascript",
                            "exec": test_script,
                        },
                    }
                ],
            })

        items.append({
            "name": endpoint_name,
            "item": folder_items,
        })

    return {
        "info": {
            "name": collection_name,
            "description": "Generated by AI API Testing Assistant",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": items,
        "variable": [
            {
                "key": "baseUrl",
                "value": "http://localhost:8000",
                "type": "string",
            }
        ],
    }


def export_to_pytest(
    test_cases: Sequence[TestCase],
    base_url: str = "http://localhost:8000",
) -> str:
    """Generate runnable pytest test code from test cases."""
    lines = [
        '"""Auto-generated API test suite generated by AI API Testing Assistant."""',
        "import json",
        "import urllib.request",
        "from urllib.error import HTTPError",
        "from urllib.parse import urlencode",
        "import pytest",
        "",
        f'BASE_URL = "{base_url.rstrip("/")}"',
        "",
    ]

    for idx, tc in enumerate(test_cases):
        clean_name = re.sub(r"[^a-zA-Z0-9_]+", "_", tc.name.lower()).strip("_")
        func_name = f"test_{idx:03d}_{clean_name}"
        expected_status = tc.expected_status or [200]

        lines.extend([
            f"def {func_name}():",
            f'    """Test: {tc.name} ({tc.method.upper()} {tc.path})"""',
            f'    path = "{tc.path}"',
            f"    path_params = {json.dumps(tc.path_params)}",
            "    for k, v in path_params.items():",
            '        path = path.replace(f"{{{k}}}", str(v))',
            f"    query_params = {json.dumps(tc.query_params)}",
            "    url = f\"{BASE_URL}{path}\"",
            "    if query_params:",
            '        url += "?" + urlencode(query_params)',
            f"    headers = {json.dumps(tc.headers)}",
            f"    body_data = {json.dumps(tc.body)}",
            '    data = json.dumps(body_data).encode("utf-8") if body_data is not None else None',
            "    if data is not None and not any(k.lower() == 'content-type' for k in headers):",
            "        headers['Content-Type'] = 'application/json'",
            f'    req = urllib.request.Request(url, data=data, headers=headers, method="{tc.method.upper()}")',
            "    status = None",
            "    try:",
            "        with urllib.request.urlopen(req, timeout=10.0) as resp:",
            "            status = resp.status",
            "    except HTTPError as exc:",
            "        status = exc.code",
            f"    assert status in {expected_status}, f\"Expected {expected_status}, got {{status}}\"",
            "",
        ])

    return "\n".join(lines)


def export_to_markdown_summary(report: dict, analysis: dict | None = None) -> str:
    """Generate a GitHub PR comment or CI/CD step summary in GitHub Flavored Markdown."""
    summary = report.get("summary", {})
    counts = summary.get("counts", {})
    pass_rate = summary.get("pass_rate")
    pass_pct = f"{round(pass_rate * 100, 1)}%" if pass_rate is not None else "N/A"

    contract_drift = summary.get("contract_violations", 0)
    sla_violations = summary.get("sla_violations", 0)

    status_badge = "🟢 PASSED" if counts.get("failed", 0) == 0 and counts.get("error", 0) == 0 else "🔴 FAILED"

    lines = [
        f"## 🧪 API Test Execution Summary: {status_badge}",
        "",
        "### 📊 Overall Metrics",
        "",
        "| Metric | Result |",
        "| :--- | :--- |",
        f"| **Total Tests Executed** | `{summary.get('total_tests', 0)}` |",
        f"| **Pass Rate** | **`{pass_pct}`** |",
        f"| **Passed** | `{counts.get('passed', 0)}` |",
        f"| **Failed** | `{counts.get('failed', 0)}` |",
        f"| **Errors** | `{counts.get('error', 0)}` |",
        f"| **Contract Drift Violations** | `{contract_drift}` |",
        f"| **SLA Violations** | `{sla_violations}` |",
        "",
        "### 📍 Breakdown by Endpoint",
        "",
        "| Method | Endpoint | Total | Passed | Failed | Status |",
        "| :--- | :--- | :---: | :---: | :---: | :---: |",
    ]

    for ep in report.get("by_endpoint", []):
        method = ep.get("method", "").upper()
        path = ep.get("path", "")
        ep_counts = ep.get("counts", {})
        p = ep_counts.get("passed", 0)
        f = ep_counts.get("failed", 0)
        err = ep_counts.get("error", 0)
        tot = sum(ep_counts.values())
        ep_status = "✅ Pass" if f == 0 and err == 0 else "❌ Fail"
        lines.append(f"| `{method}` | `{path}` | `{tot}` | `{p}` | `{f + err}` | {ep_status} |")

    if analysis:
        lines.extend([
            "",
            "### 🤖 AI Failure Analysis",
            "",
            f"> {analysis.get('summary', '')}",
            "",
        ])
        facts = analysis.get("observed_facts", [])
        if facts:
            lines.append("**Observed Facts:**")
            for fact in facts:
                lines.append(f"- {fact}")
            lines.append("")

        hypotheses = analysis.get("hypotheses", [])
        if hypotheses:
            lines.append("**Hypotheses:**")
            for h in hypotheses:
                lines.append(f"- {h}")
            lines.append("")

        recs = analysis.get("recommendations", [])
        if recs:
            lines.append("**Recommendations:**")
            for r in recs:
                lines.append(f"- {r}")
            lines.append("")

    lines.append("---")
    lines.append("*Automated report generated by [AI API Testing Assistant](https://github.com/Sanal-T/ai-api-testing-assistant)*")
    return "\n".join(lines)
