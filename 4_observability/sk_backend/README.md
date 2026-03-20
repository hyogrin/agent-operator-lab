# SK Orchestrator Backend

A **Semantic Kernel 1.41 + FastAPI** backend that powers the beauty/cosmetics chatbot from the `2_evaluation_pipeline.ipynb` notebook. It classifies user intent, selects the appropriate XML context file, and generates LLM-grounded answers via Azure OpenAI.

The evaluation pipeline uses the **Azure AI Foundry Evals API** (`azure-ai-projects>=2.0.1`) with code-based custom evaluators registered in the Foundry catalog and builtin evaluators (groundedness, coherence, relevance) for quality scoring.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                   FastAPI Server                          │
│  POST /chat ─── POST /classify ─── GET /health           │
│         │              │                                  │
│         ▼              ▼                                  │
│   ┌─────────────────────────────┐                        │
│   │       SKOrchestrator        │  ← importable module   │
│   │                             │                        │
│   │  1. classify_intent()       │  Structured JSON output│
│   │  2. _select_xml_context()   │  Intent → XML mapping  │
│   │  3. route_and_execute()     │  LLM answer generation │
│   └────────┬────────────────────┘                        │
│            │                                              │
│   ┌────────▼────────────────────┐                        │
│   │  Semantic Kernel  (1.41.0)  │                        │
│   │  ├─ AzureChatCompletion     │                        │
│   │  ├─ ProductPlugin           │→ product_contexts.xml  │
│   │  └─ RecommendationPlugin    │→ recommendation_*.xml  │
│   └─────────────────────────────┘                        │
│                                                          │
│   OpenTelemetry ──► Azure Monitor / Application Insights │
└──────────────────────────────────────────────────────────┘
```

## Components

| Module | Purpose |
|--------|---------|
| `sk_orchestrator/config.py` | Pydantic `Settings` loaded from `.env` |
| `sk_orchestrator/models.py` | `IntentType`, `IntentResult`, API schemas, `INTENT_AGENT_MAP` |
| `sk_orchestrator/context_loader.py` | `load_xml_context()` — reads and returns XML as string |
| `sk_orchestrator/plugins.py` | `ProductPlugin`, `RecommendationPlugin` — SK `@kernel_function` wrappers |
| `sk_orchestrator/orchestrator.py` | `SKOrchestrator` — core pipeline class (intent → context → answer) |
| `sk_orchestrator/main.py` | FastAPI app with `/chat`, `/classify`, `/health` endpoints |

## XML Context Files

Located at `4_observability/contexts/`:

| File | Intent | Content |
|------|--------|---------|
| `product_contexts.xml` | `product_search` | Detailed spec of 마몽드 플래시토닝 데이지 리퀴드 마스크 (1 product) |
| `recommendation_contexts.xml` | `recommendation` | 이니스프리 · COSRX · 라네즈 (3 products with rank) |

## API Reference

### `POST /chat`

Run the full pipeline — intent classification → XML context selection → LLM answer generation.

**Request**

```json
{
  "query": "마몽드 리퀴드 마스크는 어떤 피부 타입에 좋아?",
  "session_id": ""
}
```

**Response**

```json
{
  "query": "마몽드 리퀴드 마스크는 어떤 피부 타입에 좋아?",
  "intent": "product_search",
  "confidence": 0.95,
  "agent": "productAgent",
  "method": "search_products",
  "context_source": ".../contexts/product_contexts.xml",
  "answer": "마몽드 플래시토닝 데이지 리퀴드 마스크는 중성, 복합성, 지성 피부에 ..."
}
```

### `POST /classify`

Classify intent only (no LLM answer generation).

**Request** — same as `/chat`.

**Response**

```json
{
  "intent": "product_search",
  "confidence": 0.95,
  "reasoning": "User asked about a specific Mamonde product"
}
```

### `GET /health`

Returns service health status.

**Response**

```json
{
  "status": "healthy",
  "service": "sk-orchestrator-backend",
  "model": "gpt-4.1"
}
```

## Quickstart

### 1. Install dependencies

```bash
cd 4_observability/sk_backend
uv sync          # or: pip install -e .
```

### 2. Configure environment

Create a `.env` file in the repository root (or set environment variables):

```env
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/
AZURE_OPENAI_API_KEY=<key>
AZURE_OPENAI_CHAT_DEPLOYMENT_NAME=gpt-4.1
AZURE_OPENAI_API_VERSION=2025-03-01-preview
AOAI_AUTH_METHOD=key
APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=...
```

`AOAI_AUTH_METHOD` controls how the backend authenticates with Azure OpenAI:

| Value | Authentication | When to Use |
|-------|---------------|-------------|
| `key` (default) | API key (`AZURE_OPENAI_API_KEY`) | Local development, quick setup |
| `credential` | `DefaultAzureCredential` (Entra ID) | Production, managed identity, RBAC-based access |

When set to `credential`, the `AZURE_OPENAI_API_KEY` is not required. The backend uses `DefaultAzureCredential` which automatically picks up managed identity, Azure CLI login, or environment-based credentials.

### 3. Run the server

```bash
# Option A: via CLI entry point
sk-orchestrator

# Option B: via uvicorn directly
uvicorn sk_orchestrator.main:app --host 0.0.0.0 --port 8000

# Option C: via python
python -m sk_orchestrator.main

# Kill the server (if running in foreground)
kill $(lsof -ti :8000) 2>/dev/null; sleep 1
```

The API docs are available at `http://localhost:8000/docs` (Swagger UI).

### 4. Use as a Python module (from the notebook)

```python
import sys, os
sys.path.insert(0, os.path.abspath("./sk_backend"))

from sk_orchestrator import SKOrchestrator, Settings

settings = Settings()
orchestrator = SKOrchestrator(settings)

# Full pipeline
result = await orchestrator.run("여드름 피부에 좋은 제품 추천해줘")

# Intent only
intent = await orchestrator.classify_intent("교환 문의")

# XML context selection (for evaluation dataset construction)
xml_ctx, agent_span, sys_prompt, src = orchestrator.select_xml_context(intent)
```

## Intent → Agent Mapping

| Intent | Agent | Method | XML Context |
|--------|-------|--------|-------------|
| `product_search` | `productAgent` | `search_products` | `product_contexts.xml` |
| `recommendation` | `recommendAgent` | `search_recsys` | `recommendation_contexts.xml` |
| `policy` | `policyAgent` | `search_policy` | *(default prompt)* |
| `beauty` | `beautyAgent` | `search_beauty` | *(default prompt)* |

## Observability

When `APPLICATIONINSIGHTS_CONNECTION_STRING` is set, the backend automatically:

- Configures Azure Monitor OpenTelemetry exporter
- Enables Semantic Kernel OTEL diagnostics (`SEMANTICKERNEL_EXPERIMENTAL_GENAI_ENABLE_OTEL_DIAGNOSTICS`)
- Creates spans for `intent_classification`, `agent_routing`, and per-agent execution
- Records query, intent, context source, and response length as span attributes
- Flushes all pending telemetry on server shutdown

### Viewing SK Traces in Application Insights

> **Note**: Telemetry data may take **3–5 minutes** to appear in Application Insights after API calls are made.

#### 1. Transaction Search (individual requests)

Navigate to **Application Insights → Transaction search** in the Azure Portal.

- **Event types**: Select **Request**, **Dependency**, **Trace**
- **Time range**: Last 30 minutes
- Click any request (e.g., `POST /chat`) to see the end-to-end transaction with nested spans:
  - `evaluation_pipeline` → `intent_classification` → `agent_routing` → `productAgent.search_products`

#### 2. Logs (KQL Queries)

Navigate to **Application Insights → Logs** and run these Kusto queries:

**All SK orchestrator traces:**

```kql
traces
| where cloud_RoleName == "sk-orchestrator-backend"
| order by timestamp desc
| take 50
```

**LLM call details (Semantic Kernel GenAI spans):**

```kql
dependencies
| where cloud_RoleName == "sk-orchestrator-backend"
| where name has "openai" or name has "chat"
| project timestamp, name, duration, resultCode, 
          customDimensions
| order by timestamp desc
| take 20
```

**Intent classification results:**

```kql
traces
| where cloud_RoleName == "sk-orchestrator-backend"
| where customDimensions has "intent.type"
| extend intent = tostring(customDimensions["intent.type"]),
         confidence = todouble(customDimensions["intent.confidence"]),
         query = tostring(customDimensions["user.query"])
| project timestamp, query, intent, confidence
| order by timestamp desc
```

**End-to-end latency per pipeline run:**

```kql
requests
| where cloud_RoleName == "sk-orchestrator-backend"
| where name has "/chat"
| project timestamp, duration, resultCode, url
| order by timestamp desc
| take 20
```

#### 3. Application Map

Navigate to **Application Insights → Application map** to see the dependency graph:

```
Client → SK Orchestrator Backend → Azure OpenAI
```

#### 4. Live Metrics

Navigate to **Application Insights → Live metrics** to see real-time request rates, failures, and server health while the backend is running.

### Troubleshooting: No Logs Visible

| Symptom | Cause | Fix |
|---------|-------|-----|
| No data at all | `APPLICATIONINSIGHTS_CONNECTION_STRING` not set or empty | Verify `.env` file contains the connection string |
| Spans created but not exported | `configure_azure_monitor()` called **after** tracer/kernel init | Ensure OTEL env vars are set before SK kernel creation (fixed in `main.py` lifespan) |
| Data appears after long delay | Normal ingestion latency | Wait 3–5 minutes; use **Live metrics** for real-time view |
| `Non-retryable server side error: Bad Request` | Wrong InstrumentationKey in connection string | Verify the connection string matches your Application Insights resource |
| Only requests visible, no SK inner spans | `SEMANTICKERNEL_EXPERIMENTAL_GENAI_ENABLE_OTEL_DIAGNOSTICS` not set | Must be set **before** SK kernel is created (handled by `main.py` lifespan) |

## Tech Stack

| Component | Version |
|-----------|---------|
| Semantic Kernel | 1.41.0 |
| Azure AI Projects SDK | ≥ 2.0.1 |
| FastAPI | ≥ 0.115.0 |
| Uvicorn | ≥ 0.30.0 |
| Python | ≥ 3.12 |
| Pydantic | ≥ 2.0 |
| Azure Monitor OpenTelemetry | ≥ 1.6.0 |

## Evaluation Pipeline Integration

The `2_evaluation_pipeline.ipynb` notebook consumes this backend's API to run a multi-stage evaluation pipeline using the **Azure AI Foundry Evals API** (`azure-ai-projects>=2.0.1`).

### Prerequisites

| Requirement | Description |
|-------------|-------------|
| `azure-ai-projects>=2.0.1` | Required SDK for Foundry evaluator catalog and Evals API |
| **Azure AI Developer** role | Required on the Foundry resource for evaluator registration and eval creation |
| **Cognitive Services Contributor** role | Required on the Foundry resource for server-side eval runs (`temporaryDataReference`) |
| `APPLICATIONINSIGHTS_RESOURCE_ID` | Application Insights resource ID (for trace-based evaluation) |

> **Important**: To enable server-side evaluation runs with Foundry portal `report_url`, your identity needs the following roles on the **Foundry resource** (`Microsoft.CognitiveServices/accounts`). Without these roles, the notebook automatically falls back to local evaluation mode (LLM-as-judge via the Foundry OpenAI client).
>
> | Role | Purpose |
> |------|--------|
> | **Azure AI Developer** | Register custom evaluators, create eval objects, call OpenAI Evals API |
> | **Cognitive Services Contributor** | Write to internal asset store for eval run data (`temporaryDataReference`) |
>
> Assign via: **Azure Portal** → Foundry resource → **Access control (IAM)** → **Add role assignment** → select each role → select your user.
>
> In the new Foundry architecture, there is no separate storage account — the asset store is managed internally by the Foundry resource.

### Evaluation Pipeline Flow

```
golden_user_query_list.jsonl (50 labeled queries)
         │
         ▼
    POST /chat (SK Backend)
         │
         ▼
llm_result_list.jsonl (predictions + XML context + LLM response)
         │
         ▼
project_client.beta.evaluators.create_version()
  → Register code-based evaluators in Foundry Catalog
         │
         ▼
openai_client.evals.create() + evals.runs.create()
  → Run 6 evaluators (3 custom + 3 builtin) server-side
         │
         ├──► Steps 1-3: Exact-match (intent, agent, method)
         └──► Step 4: LLM-based (groundedness, coherence, relevance)
         │
         ▼
report_url → Foundry Portal + HTML Dashboard
```

### Evaluation Steps

| Step | Evaluator | Type | Metric | What It Measures |
|------|-----------|------|--------|------------------|
| 1 | `intent_accuracy` | Custom (code-based) | 0.0 / 1.0 | Intent classification exact match |
| 2 | `agent_relevance` | Custom (code-based) | 0.0 / 1.0 | Correct agent selected for the intent |
| 3 | `method_relevance` | Custom (code-based) | 0.0 / 1.0 | Correct method called on the agent |
| 4a | `groundedness` | Builtin | 1–5 | Response faithfulness to XML context |
| 4b | `coherence` | Builtin | 1–5 | Response logical consistency |
| 4c | `relevance` | Builtin | 1–5 | Response relevance to user query |

### Key SDK APIs Used

| SDK | Method | Purpose |
|-----|--------|---------|
| `azure-ai-projects` | `AIProjectClient` | Foundry project client |
| `azure-ai-projects` | `project_client.beta.evaluators.create_version()` | Register custom evaluators in catalog |
| `openai` (via Foundry) | `openai_client.evals.create()` | Create evaluation group |
| `openai` (via Foundry) | `openai_client.evals.runs.create()` | Run evaluation with JSONL data |
| `openai` (via Foundry) | `openai_client.evals.runs.output_items.list()` | Retrieve per-row results |
| `openai` (via Foundry) | `openai_client.files.create()` | Upload JSONL data file |

### Data Files

| File | Purpose |
|------|---------|
| `log/golden_user_query_list.jsonl` | 50 labeled queries (expected intent/agent/method) |
| `log/llm_result_list.jsonl` | SK Backend results (predictions + context + response) |
| `log/eval_upload.jsonl` | Formatted JSONL uploaded to Foundry for eval runs |
| `log/eval_summary.json` | Aggregated evaluation metrics |
| `log/eval_dashboard.html` | Self-contained HTML dashboard with per-row results |

### Execution Modes

The notebook supports two evaluation modes, automatically selecting the best available option:

| Mode | Trigger | Evaluators | Results |
|------|---------|-----------|---------|
| **Foundry (server-side)** | Azure AI Developer role assigned | 3 custom + 3 builtin run server-side | Foundry portal `report_url` + HTML dashboard |
| **Local (fallback)** | 403 on `temporaryDataReference` | Steps 1-3 exact-match + Steps 4 LLM-as-judge | HTML dashboard only |

### How Context Flows Through Evaluation

```
golden_user_query_list.jsonl
    │
    ▼
POST /chat → SK Backend classifies intent
    │
    ├── product_search  → product_contexts.xml loaded as context
    ├── recommendation  → recommendation_contexts.xml loaded as context
    └── policy/beauty   → no XML context (default prompt)
    │
    ▼
llm_result_list.jsonl
    │
    ├── "context" field  → XML content (for Groundedness)
    └── "response" field → LLM answer (for Coherence & Relevance)
```

- **Groundedness (4a)**: Did the LLM answer stay *faithful* to the XML context without hallucinating?
- **Coherence (4b)**: Is the response logically consistent and well-structured?
- **Relevance (4c)**: Did the response directly address the user's query?
