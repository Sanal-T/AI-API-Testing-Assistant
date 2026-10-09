# AI API Testing Assistant

A Python/FastAPI backend that parses OpenAPI documents, generates deterministic API test cases, executes them against explicitly configured targets, and summarizes results. AI analysis is an optional explanation layer; it does not determine pass or fail.

## Setup

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` to use the API documentation. `POST /upload` accepts YAML or JSON OpenAPI files up to 5 MiB. It validates the document, extracts endpoints, and returns generated test cases. Uploading a specification does not execute requests.

## Safe execution

Execution is available through `app.executor.http_executor.execute_test_case`. Callers must supply an explicit `base_url` and `allowed_hosts`. Private or local targets and mutating methods require separate opt-ins; keep those disabled except for an authorized test environment. The executor does not use OpenAPI server URLs as an implicit target.

```python
from app.executor.http_executor import execute_test_case

result = execute_test_case(
    test_case,
    "http://127.0.0.1:8001",
    allowed_hosts={"127.0.0.1"},
    allow_private_network=True,
)
```

## Reports

Pass execution results to `app.report.summary.build_execution_report(results)`. It returns JSON-serializable totals and groups by endpoint and test type. `pass_rate` is `passed / (passed + failed)`; error, unverified, and skipped cases do not enter that denominator. Reports omit response bodies and headers.

## Optional AI failure analysis

The analyzer sends only test names, method/path templates, expected and actual statuses, outcome, error category, and duration. It omits request parameters, headers, bodies, response bodies, and raw error text. Use it only when sharing this metadata with the configured provider is appropriate.

Set the API key and model in the environment before calling `analyze_failures`:

```powershell
$env:OPENAI_API_KEY = "your-api-key"
$env:OPENAI_MODEL = "your-enabled-model"
```

```python
from app.analysis.failure_analyzer import analyze_failures

analysis = analyze_failures(execution_results)
print(analysis.model_dump())
```

The analyzer uses the OpenAI Responses API with storage disabled for the request. AI output separates observed facts from hypotheses and recommendations; validate suggestions before acting on them. No API key or model call is required by the upload, generation, execution, or reporting modules.

## Tests

```powershell
venv\Scripts\python.exe -m unittest discover -s tests
```

The end-to-end test starts a loopback HTTP fixture. Run the suite in an environment that permits local socket binding.
