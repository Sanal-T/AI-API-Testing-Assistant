from fastapi import APIRouter, Response
from pydantic import BaseModel

from app.models.execution_result import TestExecutionResult
from app.models.test_case import TestCase
from app.report.exporters import (
    export_to_junit_xml,
    export_to_markdown_summary,
    export_to_postman_collection,
    export_to_pytest,
)

router = APIRouter(prefix="/export", tags=["export"])


class ExportPostmanRequest(BaseModel):
    test_cases: list[TestCase]
    collection_name: str = "API Test Collection"
    base_url: str = "{{baseUrl}}"


class ExportPytestRequest(BaseModel):
    test_cases: list[TestCase]
    base_url: str = "http://localhost:8000"


class ExportJunitRequest(BaseModel):
    results: list[TestExecutionResult]
    suite_name: str = "API Test Assistant"


class ExportMarkdownRequest(BaseModel):
    report: dict
    analysis: dict | None = None


@router.post("/postman")
def export_postman(request: ExportPostmanRequest):
    """Export test cases into Postman Collection v2.1 JSON schema."""
    return export_to_postman_collection(
        request.test_cases,
        collection_name=request.collection_name,
        base_url_var=request.base_url,
    )


@router.post("/pytest")
def export_pytest_code(request: ExportPytestRequest):
    """Export test cases into a standalone runnable pytest suite."""
    code = export_to_pytest(request.test_cases, base_url=request.base_url)
    return Response(content=code, media_type="text/x-python")


@router.post("/junit")
def export_junit(request: ExportJunitRequest):
    """Export execution results into standard JUnit XML format."""
    xml_str = export_to_junit_xml(request.results, suite_name=request.suite_name)
    return Response(content=xml_str, media_type="application/xml")


@router.post("/markdown")
def export_markdown(request: ExportMarkdownRequest):
    """Export execution report into GitHub Flavored Markdown summary."""
    md_str = export_to_markdown_summary(request.report, analysis=request.analysis)
    return Response(content=md_str, media_type="text/markdown")
