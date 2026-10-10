import argparse
import json
import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from app.analysis.failure_analyzer import analyze_failures
from app.executor.http_executor import execute_batch
from app.generator.testcase_generator import generate_test_cases
from app.models.execution_result import ExecutionOutcome
from app.models.test_case import TestCase
from app.models.test_run import TestRunRequest
from app.parser.openapi_parser import extract_endpoints, load_spec, validate_openapi_spec
from app.report.exporters import (
    export_to_junit_xml,
    export_to_markdown_summary,
    export_to_postman_collection,
    export_to_pytest,
)
from app.report.summary import build_execution_report

logger = logging.getLogger("app.cli")


def parse_header_arg(header_args: list[str] | None) -> dict[str, str]:
    headers = {}
    if not header_args:
        return headers
    for h in header_args:
        if ":" in h:
            key, val = h.split(":", 1)
            headers[key.strip()] = val.strip()
    return headers


def parse_query_arg(query_args: list[str] | None) -> dict[str, str]:
    params = {}
    if not query_args:
        return params
    for q in query_args:
        if "=" in q:
            key, val = q.split("=", 1)
            params[key.strip()] = val.strip()
    return params


def run_command(args: argparse.Namespace) -> int:
    spec_path = Path(args.spec)
    if not spec_path.is_file():
        print(f"Error: Specification file not found at '{args.spec}'", file=sys.stderr)
        return 2

    print(f"Loading specification: {spec_path.name}")
    try:
        spec = load_spec(str(spec_path))
        validate_openapi_spec(spec)
        endpoints = extract_endpoints(spec)
    except Exception as exc:
        print(f"Specification validation failed: {exc}", file=sys.stderr)
        return 2

    all_cases: list[TestCase] = []
    for ep in endpoints:
        cases = generate_test_cases(ep)
        ep["test_cases"] = cases
        all_cases.extend(cases)

    print(f"Parsed {len(endpoints)} endpoints. Generated {len(all_cases)} test cases.")
    if not all_cases:
        print("No test cases generated.", file=sys.stderr)
        return 0

    base_url = args.base_url.rstrip("/")
    parsed_url = urlsplit(base_url)
    target_host = parsed_url.hostname or ""

    if args.allowed_hosts:
        allowed_hosts = {h.strip() for h in args.allowed_hosts.split(",") if h.strip()}
    else:
        allowed_hosts = {target_host} if target_host else set()

    allow_private = args.allow_private_network
    if not allow_private and target_host in {"localhost", "127.0.0.1", "::1"}:
        allow_private = True

    cli_headers = parse_header_arg(args.header)
    cli_query = parse_query_arg(args.query)

    prepared_cases = []
    for tc in all_cases:
        headers = {**tc.headers, **cli_headers}
        query_params = {**tc.query_params, **cli_query}
        prepared_cases.append(tc.model_copy(update={
            "headers": headers,
            "query_params": query_params,
        }))

    print(f"Executing {len(prepared_cases)} tests against {base_url} (concurrency: {args.concurrency})...")
    results = execute_batch(
        prepared_cases,
        base_url,
        allowed_hosts=allowed_hosts,
        concurrency=args.concurrency,
        timeout=args.timeout,
        allow_private_network=allow_private,
        allow_mutating_methods=args.allow_mutating,
    )

    report = build_execution_report(results)
    summary = report["summary"]
    counts = summary["counts"]
    pass_rate = summary["pass_rate"]
    pass_pct = f"{round(pass_rate * 100, 1)}%" if pass_rate is not None else "N/A"

    print("\n" + "=" * 60)
    print("                EXECUTION REPORT SUMMARY")
    print("=" * 60)
    print(f"  Total Tests Executed : {summary['total_tests']}")
    print(f"  Pass Rate            : {pass_pct}")
    print(f"  Passed               : {counts['passed']}")
    print(f"  Failed               : {counts['failed']}")
    print(f"  Errors               : {counts['error']}")
    print(f"  Contract Drift       : {summary['contract_violations']}")
    print(f"  SLA Breaches         : {summary['sla_violations']}")
    print("=" * 60)

    for ep in report["by_endpoint"]:
        ep_counts = ep["counts"]
        status_flag = "PASS" if ep_counts["failed"] == 0 and ep_counts["error"] == 0 else "FAIL"
        print(f"  [{status_flag:4}] {ep['method']:6} {ep['path']:<35} ({ep_counts['passed']} passed, {ep_counts['failed'] + ep_counts['error']} failed)")

    analysis_data = None
    if args.ai_provider and (counts["failed"] > 0 or counts["error"] > 0):
        print(f"\nRequesting AI failure diagnosis ({args.ai_provider})...")
        try:
            from app.ai.providers import get_llm_provider
            provider = get_llm_provider(args.ai_provider, model=args.ai_model)
            analysis = analyze_failures(results, provider=provider)
            analysis_data = analysis.model_dump(mode="json")
            print(f"  AI Diagnosis: {analysis.summary}")
            if analysis.recommendations:
                print("  Recommendations:")
                for rec in analysis.recommendations:
                    print(f"    - {rec}")
        except Exception as exc:
            print(f"  AI diagnosis failed: {exc}")

    if args.output_junit:
        xml_content = export_to_junit_xml(results, suite_name=f"API Tests ({spec_path.stem})")
        Path(args.output_junit).write_text(xml_content, encoding="utf-8")
        print(f"Exported JUnit XML to: {args.output_junit}")

    if args.output_json:
        full_output = {"report": report, "analysis": analysis_data}
        Path(args.output_json).write_text(json.dumps(full_output, indent=2), encoding="utf-8")
        print(f"Exported JSON report to: {args.output_json}")

    if args.output_markdown:
        md_content = export_to_markdown_summary(report, analysis_data)
        Path(args.output_markdown).write_text(md_content, encoding="utf-8")
        print(f"Exported Markdown summary to: {args.output_markdown}")

    has_failures = counts["failed"] > 0 or counts["error"] > 0
    if has_failures and not args.no_exit_code:
        return 1
    return 0


def export_command(args: argparse.Namespace) -> int:
    spec_path = Path(args.spec)
    if not spec_path.is_file():
        print(f"Error: Specification file not found at '{args.spec}'", file=sys.stderr)
        return 2

    try:
        spec = load_spec(str(spec_path))
        validate_openapi_spec(spec)
        endpoints = extract_endpoints(spec)
    except Exception as exc:
        print(f"Specification validation failed: {exc}", file=sys.stderr)
        return 2

    all_cases: list[TestCase] = []
    for ep in endpoints:
        all_cases.extend(generate_test_cases(ep))

    output_path = Path(args.output)
    fmt = args.format.lower()
    base_url = args.base_url or "http://localhost:8000"

    if fmt == "postman":
        collection = export_to_postman_collection(all_cases, collection_name=f"{spec_path.stem} Collection")
        output_path.write_text(json.dumps(collection, indent=2), encoding="utf-8")
        print(f"Exported {len(all_cases)} test cases to Postman Collection v2.1: {output_path}")
    elif fmt == "pytest":
        pytest_code = export_to_pytest(all_cases, base_url=base_url)
        output_path.write_text(pytest_code, encoding="utf-8")
        print(f"Exported {len(all_cases)} test cases to runnable pytest suite: {output_path}")
    else:
        print(f"Unsupported export format: {fmt}", file=sys.stderr)
        return 2

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Headless CLI for AI API Testing Assistant",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Run subcommand
    run_parser = subparsers.add_parser("run", help="Execute OpenAPI test cases against a target URL")
    run_parser.add_argument("--spec", required=True, help="Path to OpenAPI YAML/JSON file")
    run_parser.add_argument("--base-url", required=True, help="Target API base URL (e.g. http://localhost:8000)")
    run_parser.add_argument("--allowed-hosts", default=None, help="Comma-separated allowed target hostnames")
    run_parser.add_argument("--allow-private-network", action="store_true", help="Permit localhost/private IP testing")
    run_parser.add_argument("--allow-mutating", action="store_true", default=True, help="Allow mutating POST, PUT, DELETE tests")
    run_parser.add_argument("--concurrency", type=int, default=5, help="Number of concurrent worker threads (1-20)")
    run_parser.add_argument("--timeout", type=float, default=10.0, help="Per-request timeout in seconds")
    run_parser.add_argument("-H", "--header", action="append", help="Custom request header in 'Key: Value' format (repeatable)")
    run_parser.add_argument("-q", "--query", action="append", help="Custom query parameter in 'key=value' format (repeatable)")
    run_parser.add_argument("--output-junit", default=None, help="File path to save JUnit XML report")
    run_parser.add_argument("--output-json", default=None, help="File path to save JSON execution report")
    run_parser.add_argument("--output-markdown", default=None, help="File path to save GitHub PR summary markdown")
    run_parser.add_argument("--ai-provider", default=None, help="AI provider for failure analysis (e.g. openai, gemini, anthropic, ollama)")
    run_parser.add_argument("--ai-model", default=None, help="Model name override for the AI provider")
    run_parser.add_argument("--no-exit-code", action="store_true", help="Do not exit with code 1 if tests fail")

    # Export subcommand
    export_parser = subparsers.add_parser("export", help="Export test suite to Postman Collection or pytest")
    export_parser.add_argument("--spec", required=True, help="Path to OpenAPI YAML/JSON file")
    export_parser.add_argument("--format", required=True, choices=["postman", "pytest"], help="Target export format")
    export_parser.add_argument("--output", required=True, help="Output destination file path")
    export_parser.add_argument("--base-url", default="http://localhost:8000", help="Base URL for generated tests")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return run_command(args)
    elif args.command == "export":
        return export_command(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
