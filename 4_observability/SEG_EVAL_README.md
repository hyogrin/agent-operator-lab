---
post_title: "Segment Evaluation Pipeline"
author1: "hyogrin"
post_slug: "segment-evaluation-pipeline"
microsoft_alias: "hyogrin"
featured_image: ""
categories: []
tags: ["evaluation", "azure-ai-foundry", "semantic-kernel", "application-insights"]
ai_note: "AI-assisted documentation"
summary: "Evaluation pipeline for the SK Orchestrator Backend — notebook-based and CLI-based evaluation using Azure AI Foundry Evals API with custom and builtin evaluators."
post_date: "2026-03-25"
---

## Evaluation Pipeline

This document covers the evaluation pipeline for the
[SK Orchestrator Backend](sk_backend/README.md). It includes:

1. **Notebook-based evaluation** (`2_evaluation_pipeline.ipynb`) —
   interactive, end-to-end pipeline inside a Jupyter notebook.
2. **CLI-based evaluation** (`segment-eval-pipeline.py`) —
   standalone script for CSV import and batch evaluation.

Both paths use the **Azure AI Foundry Evals API**
(`azure-ai-projects>=2.0.1`) with code-based custom evaluators
registered in the Foundry catalog and builtin evaluators
(groundedness, coherence, relevance) for quality scoring.

## Prerequisites

| Requirement | Description |
|-------------|-------------|
| `azure-ai-projects>=2.0.1` | Required SDK for Foundry evaluator catalog and Evals API |
| **Azure AI Developer** role | Required on the Foundry resource for evaluator registration and eval creation |
| **Cognitive Services Contributor** role | Required on the Foundry resource for server-side eval runs (`temporaryDataReference`) |
| `APPLICATIONINSIGHTS_RESOURCE_ID` | Application Insights resource ID (for trace-based evaluation) |

> **Important**: To enable server-side evaluation runs with Foundry portal
> `report_url`, your identity needs the following roles on the **Foundry
> resource** (`Microsoft.CognitiveServices/accounts`). Without these roles,
> the notebook automatically falls back to local evaluation mode
> (LLM-as-judge via the Foundry OpenAI client).
>
> | Role | Purpose |
> |------|--------|
> | **Azure AI Developer** | Register custom evaluators, create eval objects, call OpenAI Evals API |
> | **Cognitive Services Contributor** | Write to internal asset store for eval run data (`temporaryDataReference`) |
>
> Assign via: **Azure Portal** → Foundry resource →
> **Access control (IAM)** → **Add role assignment** → select each
> role → select your user.
>
> In the new Foundry architecture, there is no separate storage
> account — the asset store is managed internally by the Foundry
> resource.

## Evaluation Steps

| Step | Evaluator | Type | Metric | What It Measures |
|------|-----------|------|--------|------------------|
| 1 | `intent_accuracy` | Custom (code-based) | 0.0 / 1.0 | Intent classification exact match |
| 2 | `agent_relevance` | Custom (code-based) | 0.0 / 1.0 | Correct agent selected for the intent |
| 3 | `method_relevance` | Custom (code-based) | 0.0 / 1.0 | Correct method called on the agent |
| 4a | `groundedness` | Builtin | 1–5 | Response faithfulness to XML context |
| 4b | `coherence` | Builtin | 1–5 | Response logical consistency |
| 4c | `relevance` | Builtin | 1–5 | Response relevance to user query |
| 4d | `similarity` | Builtin | 1–5 | Response similarity to ground_truth |

## How Context Flows Through Evaluation

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

- **Groundedness (4a)**: Did the LLM answer stay *faithful* to the
  XML context without hallucinating?
- **Coherence (4b)**: Is the response logically consistent and
  well-structured?
- **Relevance (4c)**: Did the response directly address the user's
  query?

## Notebook Evaluation Pipeline (`2_evaluation_pipeline.ipynb`)

### Pipeline Flow

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

The notebook supports two evaluation modes, automatically selecting
the best available option:

| Mode | Trigger | Evaluators | Results |
|------|---------|-----------|---------|
| **Foundry (server-side)** | Azure AI Developer role assigned | 3 custom + 3 builtin run server-side | Foundry portal `report_url` + HTML dashboard |
| **Local (fallback)** | 403 on `temporaryDataReference` | Steps 1-3 exact-match + Steps 4 LLM-as-judge | HTML dashboard only |

## Segment Evaluation Pipeline CLI (`segment-eval-pipeline.py`)

A standalone CLI that parses Application Insights CSV exports and
runs the full Foundry evaluation pipeline without requiring a
notebook.

### Three Modes

| Mode | Description | Input | Output |
|------|-------------|-------|--------|
| `csv-import` | Parse App Insights CSV → evaluation JSONL | CSV file | `eval_dataset.jsonl` |
| `evaluate` | Run Foundry eval pipeline (Parts 4-7) | JSONL dataset | Summary JSON + HTML dashboard |
| `full` | Combined: csv-import → evaluate | CSV file | All outputs |

### Evaluation Types (`--eval-type`)

The `evaluate` command supports two evaluation types:

| Type | Description | Input | Flow |
|------|-------------|-------|------|
| `live` | Call SK Backend in real-time to collect LLM responses, then evaluate | Golden query JSONL + server URL | Queries → POST /chat → results JSONL → evaluate |
| `offline` | Evaluate pre-collected results (no server call) | Result JSONL | Read file → evaluate |

### Usage

```bash
cd 4_observability

# ── csv-import: Parse App Insights CSV ──
python segment-eval-pipeline.py csv-import \
    --csv log/application_insight_data_sample.csv \
    --output log/eval_dataset.jsonl \
    --start "2026-03-09T14:00" \
    --end "2026-03-09T15:00"
```

> **Domain expert review required after `csv-import`**:
> The output JSONL contains `expected_*` fields (copied from predicted
> values) and `ground_truth` (copied from the LLM response). A **domain
> expert must review and correct** these fields before using custom
> evaluators.
>
> **Recommended workflow**:
> 1. Run `csv-import` → generates `eval_dataset.jsonl`
> 2. Domain expert reviews and corrects `expected_intent`,
>    `expected_agent`, `expected_method`, and `ground_truth`
> 3. Save the reviewed file as
>    `golden_user_query_ground_truth_list.jsonl`
> 4. Use the reviewed file with
>    `evaluate --eval-type offline --result-data`
>
> Builtin evaluators (`groundedness`, `coherence`, `relevance`) work
> without review.

```bash
# ── evaluate (live): SK Backend → collect → evaluate ──
# Requires sk_backend running on port 8000
python segment-eval-pipeline.py evaluate \
    --eval-type live \
    --queries log/live_golden_user_query_list.jsonl \
    --server-url http://localhost:8000 \
    --evaluators intent_accuracy agent_relevance method_relevance \
                 groundedness coherence relevance \
    --sampling 5

# ── evaluate (live + local): API key only, no Foundry ──
python segment-eval-pipeline.py evaluate \
    --eval-type live \
    --queries log/live_golden_user_query_list.jsonl \
    --evaluators all \
    --sampling 10 \
    --local

# ── evaluate (offline): existing result JSONL ──
python segment-eval-pipeline.py evaluate \
    --eval-type offline \
    --result-data log/offline_golden_query_response.jsonl \
    --evaluators all

# ── evaluate (offline + sampling): limit records ──
python segment-eval-pipeline.py evaluate \
    --eval-type offline \
    --result-data log/eval_dataset.jsonl \
    --evaluators groundedness coherence \
    --sampling 20

# ── full: CSV → eval → dashboard (combined) ──
python segment-eval-pipeline.py full \
    --csv log/query_data_origin.csv \
    --evaluators all \
    --start "2026-03-09T14:00" \
    --end "2026-03-09T15:00" \
    --sampling 50
```

### Available Evaluators

| Name | Type | Metric | Description |
|------|------|--------|-------------|
| `intent_accuracy` | Custom (code) | 0.0 / 1.0 | Predicted vs expected intent exact match |
| `agent_relevance` | Custom (code) | 0.0 / 1.0 | Predicted vs expected agent exact match |
| `method_relevance` | Custom (code) | 0.0 / 1.0 | Predicted vs expected method exact match |
| `groundedness` | Builtin | 1–5 | Response faithfulness to context |
| `coherence` | Builtin | 1–5 | Response logical consistency |
| `relevance` | Builtin | 1–5 | Response relevance to query |
| `similarity` | Builtin | 1–5 | Response similarity to ground_truth (requires `ground_truth` field) |

### CSV Trace Parsing

The CLI parses Application Insights CSV exports (e.g.,
`query_data_origin.csv`) by grouping rows by `dd.trace_id` and
extracting:

| `custom_type` | Extracted As | Used For |
|---------------|-------------|----------|
| `USER_QUERY` | `query` | All evaluators |
| `AGENT_NAME` | `agent`, `method`, `intent` | Custom evaluators |
| `AGENT_OUTPUT_FORMATTED` | `context` | Groundedness, Relevance |
| `FINAL_ANSWER_RAW` | `response` | All quality evaluators |

### CLI Arguments

```
segment-eval-pipeline csv-import
  --csv         Path to App Insights CSV export (required)
  --output      Output JSONL path (default: log/eval_dataset.jsonl)
  --start       Start time filter, ISO format (optional)
  --end         End time filter, ISO format (optional)

segment-eval-pipeline evaluate
  --eval-type   live | offline (default: offline)
  --queries     Golden query JSONL path (live mode,
                default: log/golden_user_query_list.jsonl)
  --server-url  SK Backend URL (live mode,
                default: http://localhost:8000)
  --result-data Result JSONL path (offline mode,
                required for offline)
  --evaluators  Space-separated evaluator names
                (default: all except similarity).
                Use 'all' to include similarity
                (requires ground_truth).
  --sampling    Limit number of records (optional, omit for all)
  --dashboard   Output HTML dashboard path (optional)
  --local       Run locally with API key (skip Foundry upload)

segment-eval-pipeline full
  --csv         Path to App Insights CSV export (required)
  --evaluators  Space-separated evaluator names
                (default: all except similarity).
                Use 'all' to include similarity
                (requires ground_truth).
  --start       Start time filter (optional)
  --end         End time filter (optional)
  --output      Intermediate JSONL path (optional)
  --sampling    Limit number of records (optional)
  --dashboard   Output HTML dashboard path (optional)
  --local       Run locally with API key (skip Foundry upload)
```

### Golden Dataset Creation Pipeline

```
Application Insights (Azure Portal)
         │
    Export as CSV
         │
         ▼
application_insight_data_sample.csv
         │
    csv-import (segment-eval-pipeline.py)
         │
         ▼
eval_dataset.jsonl
  (expected_* = predicted, ground_truth = response)
         │
         ▼
┌────────────────────────────┐
│   Domain Expert            │
│   Review & Correct         │
│   ・expected_intent/agent  │
│   ・expected_method        │
│   ・ground_truth           │
└────────────┬───────────────┘
             ▼
golden_user_query_list.jsonl
  (verified ground-truth labels)
```

### Evaluation Pipeline Flow

**Live mode** calls the SK Backend to generate fresh LLM responses,
then evaluates them.
**Offline mode** skips the server call and evaluates a pre-collected
result JSONL directly.

```
┌─── live mode ───────────────────────────────┐
│                                              │
│  golden_user_query_list.jsonl                │
│           │                                  │
│  evaluate --eval-type live                   │
│  (POST /chat → SK Backend)                   │
│           │                                  │
│           ▼                                  │
│  llm_result_list.jsonl                       │
│  (predicted_* + context + response)          │
│                                              │
└──────────┬───────────────────────────────────┘
           │
           │  ┌─── offline mode ──────────────┐
           │  │                                │
           │  │  pre-collected result JSONL     │
           │  │  (e.g. eval_dataset.jsonl)     │
           │  │                                │
           │  └──────────┬─────────────────────┘
           │             │
           └──────┬──────┘
                  │
                  ▼
           Evaluation Engine
                  │
           ├── Part 4: Register evaluators
           ├── Part 5: Foundry eval run
           ├── Part 6: Collect results
           └── Part 7: HTML dashboard
                  │
                  ▼
  eval_summary.json + eval_dashboard.html
```
