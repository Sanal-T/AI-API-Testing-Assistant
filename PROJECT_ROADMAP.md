# AI API Testing Assistant — Status & Roadmap

> **Document Version:** 1.0.0  
> **Repository:** [ai-api-testing-assistant](https://github.com/Sanal-T/ai-api-testing-assistant)  
> **Last Updated:** October 2026  

---

## Executive Summary

The **AI API Testing Assistant** is currently a functional, deterministic OpenAPI-based test generator and execution engine with safety guardrails (SSRF protection, allowlisting, credential scrubbing) and post-mortem AI failure diagnosis. 

While the foundation is solid with 47 passing tests, the system is primarily a **deterministic contract fuzzer with an AI explanation layer**. To become a true **AI API Testing Assistant**, it must evolve to use AI for *semantic test generation*, *stateful multi-step API chaining*, *response contract validation*, and *multi-model support*.

---

## 1. What Has Been Done (Current Implementation)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           CURRENT PIPELINE (BUILT & TESTED)                     │
├───────────────┬──────────────────┬─────────────────┬─────────────┬──────────────┤
│ 1. Ingestion  │ 2. Parser        │ 3. Generator    │ 4. Executor │ 5. Diagnosis │
│ Upload YAML/  │ Dereference $ref │ Positive/Neg/   │ Safe HTTP   │ OpenAI       │
│ JSON (5 MiB)  │ & Validate Spec  │ Auth Boundaries │ Execution   │ Post-Mortem  │
└───────────────┴──────────────────┴─────────────────┴─────────────┴──────────────┘
```

### 1.1 OpenAPI Parsing & Dereferencing
* **Files:** [`app/parser/openapi_parser.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/parser/openapi_parser.py), [`app/parser/__init__.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/parser/__init__.py)
* **Capabilities:**
  * Loads YAML and JSON specifications up to 5 MiB with standard-compliant validation via `openapi-spec-validator`.
  * Implements recursive JSON pointer resolution (`resolve_schema_ref`) supporting local `$ref` targets across schemas, properties, array items, and composition blocks (`allOf`, `anyOf`, `oneOf`).
  * Circular reference detection and protection.
  * Operation parameter inheritance and extraction across path, query, header, and cookie scopes.
  * Normalization of declared security schemes (API Key, HTTP Basic, HTTP Bearer, OAuth 2.0, OpenID Connect).

### 1.2 Deterministic Test Case Generation
* **Files:** [`app/generator/testcase_generator.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/generator/testcase_generator.py), [`app/models/test_case.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/models/test_case.py)
* **Capabilities:**
  * **Positive Testing:** Generates compliant request payloads adhering to data types, formats (`email`, `uuid`, `date-time`, `ipv4`, `uri`), enums, and defaults. Supports omitting optional request bodies.
  * **Negative Schema Boundary Testing:**
    * Missing required object fields.
    * Numeric boundary breaches (`minimum - 1`, `maximum + 1`, exclusive boundaries).
    * String length breaches (`minLength - 1`, `maxLength + 1`).
    * Format invalidation (e.g. malformed emails, invalid UUIDs).
    * Null injection into non-nullable fields.
    * Array size constraints (`minItems - 1`, `maxItems + 1`).
  * **Parameter Testing:** Isolated query and header negative tests omitting required values or injecting boundary violations.
  * **Authentication Testing:** Generates missing-authentication negative cases by systematically stripping declared credentials.

### 1.3 Safe HTTP Execution Engine
* **Files:** [`app/executor/http_executor.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/executor/http_executor.py), [`app/models/execution_result.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/models/execution_result.py)
* **Capabilities:**
  * **SSRF Guardrails:** Blocks requests to local, private, loopback, link-local, and reserved networks by default via DNS resolution and IP address classification.
  * **Explicit Allowlisting:** Requires hostnames to be explicitly declared in `allowed_hosts`.
  * **Mutation Protection:** Mutating verbs (`POST`, `PUT`, `PATCH`, `DELETE`) are strictly blocked unless `allow_mutating_methods` is explicitly granted.
  * **Credential Masking:** Removes sensitive headers (`Set-Cookie`, `Authorization`, `Proxy-Authenticate`) from execution records.
  * **Redirect & Memory Safety:** Disables automatic HTTP redirects to avoid redirect credential leakage; caps response body reads at 1 MB to prevent out-of-memory exhaustion.
  * **Timing:** High-precision duration measurement using `time.perf_counter`.

### 1.4 Reporting & Aggregation Engine
* **Files:** [`app/report/summary.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/report/summary.py)
* **Capabilities:**
  * Aggregates execution outcomes: `passed`, `failed`, `error`, `unverified`, `skipped`.
  * Calculates assertion pass rate based exclusively on evaluated assertions: `passed / (passed + failed)`.
  * Organizes breakdowns both by endpoint (`method` + `path`) and by test type (`positive`, `negative`).
  * Strips response bodies and raw auth headers to keep reports portable and credential-safe.

### 1.5 Privacy-First AI Failure Analysis
* **Files:** [`app/analysis/failure_analyzer.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/analysis/failure_analyzer.py)
* **Capabilities:**
  * Client implementation for the OpenAI Responses API.
  * Privacy-first evidence compilation: Sends **only** test names, methods, URL templates, expected vs actual status codes, error classifications, and durations.
  * **Zero secret exposure:** Never transmits request payloads, query parameters, authorization headers, or response bodies to external AI providers.
  * Structured output parsing: Classifies observations into `summary`, `observed_facts`, `hypotheses`, and `recommendations`.

### 1.6 Web User Interface
* **Files:** [`app/ui/index.html`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/ui/index.html), [`app/main.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/main.py)
* **Capabilities:**
  * Single-page interface served directly by FastAPI.
  * Allows drag-and-drop or file upload of OpenAPI YAML/JSON specs.
  * Interactive test selection: Filter, select all, or cherry-pick specific endpoints and test cases.
  * Target configuration modal: Base URL, allowed hosts, custom headers/query parameters, timeout, and security toggles.
  * Live status reporting, metric scorecards, endpoint result breakdown, and AI failure analysis display.
  * Downloadable JSON report export.

### 1.7 Testing & Quality Assurance
* **Files:** [`tests/`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/tests)
* **Capabilities:**
  * 47 unit and integration tests passing in < 1 second.
  * Covers parsing, test generation, schema dereferencing, HTTP execution with local sockets, report generation, API endpoints (`/upload`, `/run`), and AI evidence sanitation.

---

## 2. Codebase Audit Summary (Handoff Checks)

| Category | Finding | Status |
| :--- | :--- | :---: |
| **Version Control** | Git repository on `main` branch, tracking remote GitHub repo. 10+ clean, descriptive commits. `.gitignore` active. | **PASS** |
| **Hardcoded Secrets** | No API keys, passwords, or live tokens hardcoded. `OPENAI_API_KEY` retrieved strictly via `os.environ`. Mock strings used in tests. | **PASS** |
| **Dead / Redundant Code** | Empty folders (`app/executer/`, `app/utils/`). Duplicated constants (`_MUTATING_METHODS`, `_BLOCKED_HEADERS`). Double target validation. | **NEEDS CLEANUP** |
| **Error Tracking** | No server-side logging (`logging` module unused). AI exceptions suppressed without stack traces. No Sentry/Loguru integration. | **MISSING** |
| **Access Control** | No authentication/authorization. Uploaded specs persist permanently in `uploads/` without cleanup. Open SSRF proxy risks. | **ACTION REQUIRED** |

---

## 3. What Needs To Be Done (Development Roadmap)

To elevate this project from a deterministic contract tester to a **complete, intelligent, production-grade AI API Testing Assistant**, the following tasks must be completed.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        ROADMAP TO MATURITY                             │
├────────────────────────┬───────────────────────┬───────────────────────┤
│    Phase 1: Hygiene    │  Phase 2: Core AI     │  Phase 3: Workflows   │
├────────────────────────┼───────────────────────┼───────────────────────┤
│ • In-memory parsing    │ • Semantic AI payload │ • Multi-step chains   │
│ • Structured logging   │ • Natural lang tests  │ • Variable extraction │
│ • Clean dead code      │ • Business logic fuzz │ • Auth state handoffs │
├────────────────────────┼───────────────────────┼───────────────────────┤
│   Phase 4: Contract    │  Phase 5: Agnostic    │  Phase 6: Platform    │
├────────────────────────┼───────────────────────┼───────────────────────┤
│ • Response schema val  │ • Google Gemini SDK   │ • Async HTTP engine   │
│ • JSONPath assertions  │ • Anthropic Claude    │ • CLI & CI/CD exports │
│ • Latency & SLA rules  │ • Local LLMs (Ollama) │ • Modernized UI       │
└────────────────────────┴───────────────────────┴───────────────────────┘
```

---

### Phase 1: Codebase Hygiene, Security & Observability (High Priority)
- [x] **Fix Upload Storage Leakage ([`app/api/upload.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/api/upload.py))**:
  - Replaced disk writes to `uploads/` with in-memory parsing using `load_spec_from_string`.
  - Prevented user specification accumulation and proprietary data retention on the server.
- [x] **Remove Dead Code & Directories**:
  - Deleted unused directories [`app/executer/`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/executer) and [`app/utils/`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/utils).
  - Deleted test artifacts inside `uploads/` (`package.json`, `petstore.yaml`, `sample_api.yaml`).
  - Consolidated `_MUTATING_METHODS`, `_BLOCKED_HEADERS`, and execution limits into a single shared constants file [`app/constants.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/constants.py).
  - Added missing `__init__.py` files to all packages.
- [x] **Implement Structured Error Logging**:
  - Configured standard Python `logging` in [`app/main.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/main.py).
  - Added a global FastAPI `@app.exception_handler(Exception)` that captures full stack traces and returns sanitised error responses.
  - Preserved exception stack traces in [`app/api/test_runs.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/api/test_runs.py) for AI provider errors.
- [x] **Add Configuration & Environment Template**:
  - Created [`.env.example`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/.env.example) documenting `OPENAI_API_KEY`, `OPENAI_MODEL`, `ALLOWED_HOSTS`, and `LOG_LEVEL`.

---

### Phase 2: True AI-Powered Test Case Generation (Core Value Proposition)
- [x] **Semantic AI Payload Generation**:
  - Implemented [`app/generator/ai_generator.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/generator/ai_generator.py) synthesizing domain-realistic payloads based on endpoint schemas, parameter metadata, and field names.
- [x] **Business Logic & Edge-Case Synthesis**:
  - Configured structured prompt engineering for adversarial test generation (boundary attacks, state tampering, privilege escalation).
  - Enhanced [`TestCase`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/models/test_case.py#L6) model with `rationale` to explain test intent.
- [x] **Natural Language Prompt-to-Test Interface**:
  - Added `POST /generate/ai` endpoint in [`app/api/generate.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/api/generate.py) accepting natural language prompts (`user_prompt`) and returning executable `TestCase` objects.
  - Integrated AI prompt box into [`app/ui/index.html`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/ui/index.html) allowing users to synthesize edge cases on demand and execute them seamlessly.

---

### Phase 3: Response Contract Validation & Advanced Assertions
- [x] **Full Response Body Schema Validation**:
  - Implemented [`app/executor/contract_validator.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/executor/contract_validator.py) using `jsonschema.Draft202012Validator`.
  - Flags contract drift and schema violations even when an API returns an HTTP `200 OK` status.
  - Automatically auto-links OpenAPI response schemas to generated positive test cases in [`app/generator/testcase_generator.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/generator/testcase_generator.py).
- [x] **JSONPath & Deep Assertions**:
  - Evaluates dot-notation JSONPath expressions with `equals`, `contains`, `exists`, and `min_count` rules.
- [x] **Header & Content-Type Assertions**:
  - Validates required response headers and case-insensitive values (e.g. `Content-Type: application/json`).
- [x] **Latency & SLA Assertions**:
  - Flags tests exceeding `max_duration_ms` thresholds with SLA breach warnings in the execution report and UI.

---

### Phase 4: Multi-Step Stateful API Chaining & Workflows
- [x] **Workflow & Dependency Engine**:
  - Implemented [`app/executor/workflow_runner.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/executor/workflow_runner.py) supporting sequential execution of chained test steps with stop-on-failure controls and teardown hooks.
- [x] **Variable Extraction & Dynamic Injection**:
  - Dot-notation extraction from JSON response bodies and response headers via [`VariableExtractor`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/models/workflow.py).
  - Recursive template interpolation resolving `{{variable_name}}` placeholders in paths, headers, query parameters, and bodies.
- [x] **Automated Teardown & Environment Cleanup**:
  - Guaranteed execution of teardown steps (e.g. `DELETE /resource/{id}`) to clean up mutated resources after tests.
  - Auto-synthesis of full CRUD lifecycle workflows via [`app/generator/workflow_generator.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/generator/workflow_generator.py) and interactive execution in the browser UI.

---

### Phase 5: Multi-Model & Local LLM Support
- [x] **Provider Abstraction Layer**:
  - Implemented [`app/ai/providers.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/ai/providers.py) unifying AI completion across:
    - **Google Gemini** (Gemini 2.0 Flash / Pro via Generative Language API).
    - **Anthropic Claude** (Claude 3.5 Sonnet / Haiku via Messages API).
    - **Local / On-Premise LLMs** (Ollama, vLLM, LocalAI) without cloud keys or external internet connectivity.
    - **OpenAI** (GPT-4o, GPT-4o-mini).
- [x] **Configurable Model Settings**:
  - Created provider factory `get_llm_provider()` with environment auto-detection (`AI_PROVIDER`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `LOCAL_LLM_URL`).
  - Added multi-model support to [`app/analysis/failure_analyzer.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/analysis/failure_analyzer.py) and [`app/generator/ai_generator.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/generator/ai_generator.py).
  - Documented configurations in [`.env.example`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/.env.example).

---

### Phase 6: Performance & Engine Modernization
- [x] **Concurrent Batch Execution Engine**:
  - Implemented `execute_batch` in [`app/executor/http_executor.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/executor/http_executor.py) using `concurrent.futures.ThreadPoolExecutor` with configurable concurrency (1 to 20 workers, default 5).
  - Preserves input order while executing requests in parallel with full error containment.
- [x] **Real-Time Execution Streaming (SSE)**:
  - Added `execute_batch_stream` generator yielding test results as soon as each individual worker completes.
  - Added `POST /run/stream` in [`app/api/test_runs.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/api/test_runs.py) utilizing Starlette's `StreamingResponse` emitting `data: {"type": "progress", ...}` and final `data: {"type": "complete", ...}` events.
- [x] **UI Live Streaming Progress**:
  - Updated [`app/ui/index.html`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/ui/index.html) with a concurrency worker pool selector and live SSE progress meter showing real-time percentages and test-by-test completion badges.

---

### Phase 7: Developer Experience, CLI & CI/CD Integration
- [x] **Headless CLI Tool**:
  - Implemented [`app/cli.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/cli.py) with subcommands:
    - `python -m app.cli run --spec openapi.yaml --base-url https://api.staging.internal --output-junit results.xml --output-markdown summary.md`
    - `python -m app.cli export --spec openapi.yaml --format postman --output postman_collection.json`
    - `python -m app.cli export --spec openapi.yaml --format pytest --output test_generated_api.py`
  - Supports configurable concurrency, custom headers (`-H`), query parameters (`-q`), AI failure diagnosis, and CI/CD exit codes.
- [x] **CI/CD Exporters ([`app/report/exporters.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/report/exporters.py))**:
  - Standard **JUnit XML** exporter natively recognized by GitHub Actions, GitLab CI, Azure DevOps, and Jenkins.
  - **GitHub Markdown PR / Step Summary** generator with scorecard metrics, status badges, endpoint tables, and AI recommendations.
- [x] **Postman & pytest Code Generation**:
  - Export test suites directly to **Postman Collection (v2.1)** JSON with embedded test scripts and schema compliance.
  - Export runnable standalone **pytest** test files (`test_generated_api.py`).
- [x] **HTTP Export Endpoints & Browser UI Actions**:
  - Added `/export/postman`, `/export/pytest`, `/export/junit`, and `/export/markdown` endpoints in [`app/api/export.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/api/export.py).
  - Integrated export buttons into [`app/ui/index.html`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/ui/index.html) for one-click browser downloads.

---

### Phase 8: UI / UX Modernization
- [x] **Rich Interactive Response Inspector**:
  - Implemented collapsible accordion inspector for execution results in [`app/ui/index.html`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/ui/index.html).
  - Displays expected vs actual HTTP status, precise latency (ms), contract validation drift violations, SLA threshold warnings, diagnostic error messages, and re-run triggers.
- [x] **Editable Test Case Payloads**:
  - Added an interactive modal editor enabling users to edit test names, expected status codes, request bodies, query params, and headers in-place.
  - Added individual "▶ Run Single" test buttons for immediate isolated endpoint execution and validation without full batch runs.
- [x] **Dark Mode & Modern Design System**:
  - Implemented full Dark & Light mode theme support with persistent `localStorage` toggle and sleek CSS tokens.
  - Added real-time test case search & filter pills (`All`, `Positive`, `Negative`, `AI Generated`).
  - Added animated execution progress bar tracking concurrent worker pool completion.

---

## 4. Suggested Implementation Schedule

| Sprint | Focus | Core Deliverables |
| :---: | :--- | :--- |
| **Sprint 1** | **Hygiene & Security** | In-memory upload parsing, delete dead directories, structured logging, `.env.example`. |
| **Sprint 2** | **Contract Validation** | Response body JSON schema validation, latency assertions, status assertion enhancements. |
| **Sprint 3** | **AI Test Generation** | Semantic payload synthesis, Gemini & OpenAI prompt engineering for business logic edge cases. |
| **Sprint 4** | **Async Engine & Workflows** | Migrate to `httpx.AsyncClient`, implement multi-step sequence chaining & variable capture. |
| **Sprint 5** | **CI/CD & CLI** | Command-line runner, JUnit XML exporter, Postman collection exporter. |
| **Sprint 6** | **UI Modernization** | Live SSE execution updates, interactive JSON viewer, editable test payloads. |
