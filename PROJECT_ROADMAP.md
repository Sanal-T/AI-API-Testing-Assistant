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
- [ ] **Semantic AI Payload Generation**:
  - Replace static fallback values (`"sample"`, `0`, `1`) with contextually accurate domain data synthesized by an LLM based on field names and schema descriptions.
  - Examples: Generating realistic postal codes for `zip_code`, realistic ISO currencies for `currency`, real medical codes for `icd_code`.
- [ ] **Business Logic & Edge-Case Synthesis**:
  - Instruct the AI to inspect endpoint combinations and generate domain-specific adversarial cases:
    - Purchasing with negative quantities or zero balances.
    - Invalid state transitions (e.g. attempting to cancel an already-delivered order).
    - Privilege escalation payloads (e.g. attempting to modify `role: "admin"` in user update payloads).
- [ ] **Natural Language Prompt-to-Test Interface**:
  - Enable users to prompt the assistant in plain English:
    - *"Generate 10 security-focused tests for the billing and subscription endpoints."*
    - *"Test inventory race conditions when two orders request the same item."*
  - Automatically parse the AI output into executable [`TestCase`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/models/test_case.py#L6) schemas.

---

### Phase 3: Response Contract Validation & Advanced Assertions
- [ ] **Full Response Body Schema Validation**:
  - Validate actual JSON response bodies against the declared OpenAPI `response_schemas` using `jsonschema`.
  - Flag contract drift when an API returns undocumented properties or incorrect data types despite a `200 OK` status.
- [ ] **JSONPath & Deep Assertions**:
  - Allow test cases to assert specific payload values (e.g. `$.status == "active"`, `$.data.id` is not null).
- [ ] **Header & Content-Type Assertions**:
  - Validate that returned headers match specifications (e.g. `Content-Type: application/json; charset=utf-8`, presence of `Cache-Control` or security headers).
- [ ] **Latency & SLA Assertions**:
  - Allow setting max response duration rules (e.g. `max_duration_ms: 500`). Fail or warn when endpoints violate SLAs.

---

### Phase 4: Multi-Step Stateful API Chaining & Workflows
- [ ] **Workflow & Dependency Engine**:
  - Support multi-step ordered test scenarios (e.g. `POST /auth/login` $\rightarrow$ `POST /items` $\rightarrow$ `GET /items/{id}` $\rightarrow$ `DELETE /items/{id}`).
- [ ] **Variable Extraction & Dynamic Injection**:
  - Extract dynamic values from preceding responses (e.g., extracting an auth token `$.access_token` or entity ID `$.id`).
  - Inject extracted variables into subsequent headers, URL paths, query parameters, or request bodies.
- [ ] **Automated Teardown & Environment Cleanup**:
  - Ensure data created during mutating test suites is cleaned up by automatically executing matching `DELETE` requests.

---

### Phase 5: Multi-Model & Local LLM Support
- [ ] **Provider Abstraction Layer**:
  - Refactor [`app/analysis/failure_analyzer.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/analysis/failure_analyzer.py) to support multiple AI providers behind an `AnalysisProvider` interface:
    - **Google Gemini** (Gemini 2.0 Flash / Pro via official SDK).
    - **Anthropic Claude** (Claude 3.5 Sonnet).
    - **Local Models via Ollama / vLLM / LiteLLM** (allows running entirely on-premises for enterprise privacy).
- [ ] **Configurable Model Settings**:
  - Allow users to select the provider, model name, and temperature directly from the UI or environment.

---

### Phase 6: Performance & Engine Modernization
- [ ] **Asynchronous HTTP Client**:
  - Replace blocking `urllib.request` in [`app/executor/http_executor.py`](file:///c:/Users/SANAL/Desktop/AI-API-Testing-Assistant/app/executor/http_executor.py) with `httpx.AsyncClient`.
  - Implement concurrent batch execution with a configurable concurrency limit (e.g. 5–10 concurrent requests) to speed up test execution by 5–10x.
- [ ] **Real-time Execution Streaming**:
  - Stream test execution results live to the UI via Server-Sent Events (SSE) or WebSockets instead of waiting for the entire batch to complete.

---

### Phase 7: Developer Experience, CLI & CI/CD Integration
- [ ] **Headless CLI Tool**:
  - Build a terminal runner:
    ```bash
    python -m app.cli run --spec openapi.yaml --base-url https://api.staging.internal --output-junit results.xml
    ```
- [ ] **CI/CD Exporters**:
  - Export test execution results in **JUnit XML** format for native rendering in GitHub Actions, GitLab CI, and Azure DevOps.
  - Generate GitHub PR comment summaries with pass rates and AI recommendations.
- [ ] **Export to Postman & pytest**:
  - Export generated test collections directly to **Postman Collection (v2.1)** JSON format.
  - Export tests to a runnable **pytest** test suite (`test_generated_api.py`).

---

### Phase 8: UI / UX Modernization
- [ ] **Rich Interactive Response Inspector**:
  - Add collapsible, syntax-highlighted request and response viewers with pretty-printed JSON and status badges.
- [ ] **Editable Test Case Payloads**:
  - Allow users to click into any generated test case in the browser, tweak the JSON body or headers, and re-run on demand.
- [ ] **Dark Mode & Modern Design System**:
  - Modernize the interface with a refined dark/light theme, progress bars, and filterable search for endpoints.

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
