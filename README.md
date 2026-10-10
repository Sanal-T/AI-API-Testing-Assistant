# ◈ AI API Testing Assistant

An autonomous, contract-aware, multi-model API testing platform built with Python & FastAPI. 

It parses OpenAPI 3.0 / Swagger specifications, synthesizes deterministic and AI-powered edge-case test suites, executes tests concurrently with real-time SSE streaming, validates response contracts (JSON Schema Draft 2020-12 & SLA checks), orchestrates multi-step stateful CRUD workflows with variable chaining, and exports native test reports for CI/CD pipelines (JUnit XML, Postman v2.1, pytest, and GitHub Markdown).

---

## ⚡ Key Capabilities

- **✨ Dual Test Generation Engine**:
  - **Deterministic Fuzzing**: Schema-compliant positive tests, type mismatch attacks, boundary violations (`min/max`, `minLength/maxLength`), null injection, array constraints, and authentication stripping.
  - **Semantic AI Generation**: Generates domain-aware edge cases (negative balances, IDOR vulnerabilities, SQLi/XSS boundaries, edge timestamps) using Gemini, Claude, OpenAI, or local Ollama.
- **🛡️ Response Contract Validation & SLA Assertions**:
  - Validates API responses against OpenAPI JSON Schemas (`jsonschema.Draft202012Validator`).
  - Flags **Contract Drift** and **SLA latency breaches** even when APIs return `200 OK`.
- **🔄 Multi-Step Stateful Workflows (CRUD Chaining)**:
  - Automates dependent sequence testing (e.g. `POST /item` ➔ extract `{{id}}` ➔ `GET /item/{{id}}` ➔ `PUT` ➔ `DELETE`).
  - Guaranteed teardown execution for zero test residue.
- **🤖 Multi-Model & Local LLM Layer**:
  - Supports **Google Gemini** (Gemini 2.0 Flash/Pro), **Anthropic Claude** (Claude 3.5 Sonnet), **OpenAI** (GPT-4o), and **Local LLMs** (Ollama, vLLM, LocalAI) without cloud dependencies.
- **🚀 Concurrent Batch Engine & Real-Time SSE Streaming**:
  - Configurable worker pools (1–20 concurrent threads) with order preservation.
  - Live Server-Sent Events (`POST /run/stream`) streaming real-time progress.
- **💻 Headless CLI & CI/CD Exporters**:
  - CLI runner for automation: `python -m app.cli run --spec openapi.yaml --base-url https://api.staging.internal --output-junit results.xml`
  - Multi-format exporters: **JUnit XML**, **Postman Collection v2.1**, standalone runnable **pytest** files, and **GitHub PR Markdown summaries**.
- **🎨 Modern Dark/Light Web Interface**:
  - Refined developer-first UI with persistent Dark/Light mode, live search & category filters, in-place test payload editor, single-test runner, and expandable response inspector.

---

## 🚀 Quick Start

### 1. Installation

```powershell
# Clone the repository
git clone https://github.com/Sanal-T/ai-api-testing-assistant.git
cd ai-api-testing-assistant

# Activate the virtual environment
.\venv\Scripts\Activate.ps1

# (Optional) Install dependencies if setting up a fresh environment
pip install -r requirements.txt
```

### 2. Launch the Web Interface

```powershell
python -m uvicorn app.main:app --reload
```
Navigate to `http://127.0.0.1:8000` in your browser. API documentation is available at `http://127.0.0.1:8000/docs`.

---

## 🤖 Configuring AI Providers

Copy the example environment configuration:
```powershell
cp .env.example .env
```

Configure your preferred AI provider in `.env`:

```ini
# Provider options: "gemini", "anthropic", "openai", "ollama"
AI_PROVIDER=gemini

# Google Gemini (Default)
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-2.0-flash

# Anthropic Claude
ANTHROPIC_API_KEY=your-anthropic-api-key
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022

# OpenAI
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-4o-mini

# Zero-Cloud Local LLM (Ollama / vLLM / LocalAI)
LOCAL_LLM_URL=http://localhost:11434/v1
LOCAL_LLM_MODEL=llama3.2
```

---

## 💻 Headless CLI & CI/CD Automation

Run end-to-end API tests directly in CI/CD pipelines (GitHub Actions, GitLab CI, Azure DevOps, Jenkins) without opening a browser:

### Execute Tests & Export Reports
```powershell
python -m app.cli run `
  --spec petstore.yaml `
  --base-url http://127.0.0.1:8000 `
  --concurrency 5 `
  --output-junit results.xml `
  --output-markdown summary.md `
  --output-json report.json
```

### Export Test Suite to Postman or pytest
```powershell
# Export to Postman Collection v2.1
python -m app.cli export --spec petstore.yaml --format postman --output postman_collection.json

# Export to runnable standalone pytest test file
python -m app.cli export --spec petstore.yaml --format pytest --output test_generated_api.py
```

### CLI Command Reference
| Option | Description | Default |
| :--- | :--- | :---: |
| `--spec` | Path to OpenAPI YAML or JSON specification | *Required* |
| `--base-url` | Target API base URL | *Required* |
| `--allowed-hosts` | Comma-separated allowed target hostnames | Base URL host |
| `--allow-private-network` | Permit localhost & private subnet execution | `False` |
| `--concurrency` | Number of parallel worker threads (1–20) | `5` |
| `--timeout` | Per-request timeout in seconds | `10.0` |
| `-H, --header` | Custom request headers (repeatable e.g. `-H "Authorization: Bearer token"`) | None |
| `-q, --query` | Custom query parameters (repeatable) | None |
| `--output-junit` | File path to write standard JUnit XML report | None |
| `--output-markdown` | File path to write GitHub PR / Step summary markdown | None |
| `--output-json` | File path to write raw JSON report | None |
| `--ai-provider` | Provider for AI failure analysis (`gemini`, `anthropic`, `openai`, `ollama`) | None |
| `--no-exit-code` | Prevent non-zero exit code on test failure | `False` |

---

## 🛡️ Built-in Security Guardrails

1. **SSRF Guardrails**: Blocks requests to local, private, loopback, link-local, and reserved networks by default via DNS resolution and IP address classification.
2. **Explicit Allowlisting**: Requires target hostnames to be explicitly declared in `allowed_hosts`.
3. **Mutation Protection**: State-changing HTTP verbs (`POST`, `PUT`, `PATCH`, `DELETE`) are strictly blocked unless `allow_mutating_methods` is explicitly opted into.
4. **Credential Scrubbing**: Sensitive headers (`Authorization`, `Set-Cookie`, `Proxy-Authenticate`) and sensitive response bodies are stripped from execution reports.
5. **Zero Secret Leakage to AI**: AI failure diagnosis receives only test metadata, endpoint paths, duration, and status codes—**never** credentials, secrets, or raw request/response payloads.

---

## 🧪 Running the Test Suite

```powershell
# Run the complete automated test suite
python -m unittest discover tests
```

---

## 📁 Project Architecture

```
ai-api-testing-assistant/
├── app/
│   ├── ai/               # Multi-model LLM abstraction (Gemini, Claude, OpenAI, Ollama)
│   ├── analysis/         # Privacy-conscious AI failure diagnostic engine
│   ├── api/              # FastAPI routers (/upload, /run, /generate, /workflows, /export)
│   ├── executor/         # HTTP executor, thread pool batch runner, and contract validator
│   ├── generator/        # Deterministic boundary fuzzer and semantic AI generator
│   ├── models/           # Pydantic data schemas (TestCase, ExecutionResult, Workflow, etc.)
│   ├── parser/           # OpenAPI 3.0 / Swagger recursive JSON pointer dereferencer
│   ├── report/           # Metrics summarizer, JUnit XML, Postman, and pytest exporters
│   ├── ui/               # Modern dark/light single-page web application
│   ├── cli.py            # Headless CLI entrypoint for terminal and CI/CD runs
│   ├── constants.py      # Runtime limits and security guardrails
│   └── main.py           # Application entrypoint & exception handling
├── tests/                # Comprehensive unit, integration, and E2E test suites
├── requirements.txt      # Project dependencies
└── PROJECT_ROADMAP.md    # Multi-phase engineering roadmap and architecture status
```
