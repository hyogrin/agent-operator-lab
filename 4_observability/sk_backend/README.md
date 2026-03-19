# SK Orchestrator Backend

A **Semantic Kernel 1.41 + FastAPI** backend that powers the beauty/cosmetics chatbot from the `2_evaluation_pipeline.ipynb` notebook. It classifies user intent, selects the appropriate XML context file, and generates LLM-grounded answers via Azure OpenAI.

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
APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=...
```

### 3. Run the server

```bash
# Option A: via CLI entry point
sk-orchestrator

# Option B: via uvicorn directly
uvicorn sk_orchestrator.main:app --host 0.0.0.0 --port 8000

# Option C: via python
python -m sk_orchestrator.main
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
| FastAPI | ≥ 0.115.0 |
| Uvicorn | ≥ 0.30.0 |
| Python | ≥ 3.12 |
| Pydantic | ≥ 2.0 |
| Azure Monitor OpenTelemetry | ≥ 1.6.0 |

## Evaluation Pipeline Integration

The `2_evaluation_pipeline.ipynb` notebook consumes this backend's API to run a multi-stage evaluation pipeline using the Azure AI Evaluation SDK.

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
         ├──► Step 1: Intent Accuracy   (custom exact match)
         ├──► Step 2: Agent Relevance   (custom evaluator)
         ├──► Step 3: Method Relevance  (custom evaluator)
         ├──► Step 4a: Retrieval        (pre-built, query vs context)
         └──► Step 4b: Groundedness     (pre-built, response vs context)
```

### Evaluation Steps

| Step | Evaluator | Metric | What it measures |
|------|-----------|--------|------------------|
| 1 | `IntentAccuracyEvaluator` (custom) | `intent_accuracy` | Intent classification exact match |
| 2 | `AgentRelevanceEvaluator` (custom) | `agent_relevance` | Correct agent selected for the intent |
| 3 | `MethodRelevanceEvaluator` (custom) | `method_relevance` | Correct method called on the agent |
| 4a | `RetrievalEvaluator` (pre-built) | `retrieval` | XML context relevance to query (1-5) |
| 4b | `GroundednessEvaluator` (pre-built) | `groundedness` | Response faithfulness to XML context (1-5) |

### Data Files

| File | Purpose |
|------|---------|
| `log/golden_user_query_list.jsonl` | 50 labeled queries (expected intent/agent/method) |
| `log/llm_result_list.jsonl` | SK Backend results (predictions + context + response) |
| `log/eval_step*.json` | Per-step evaluation results |

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
    ├── "context" field  → XML content (for Retrieval & Groundedness)
    └── "response" field → LLM answer (for Groundedness)
```

- **Retrieval (4a)**: Did the intent-based routing select the *right* XML context for the query?
- **Groundedness (4b)**: Did the LLM answer stay *faithful* to the XML context without hallucinating?
