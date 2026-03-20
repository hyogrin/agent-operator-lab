#!/usr/bin/env python3
"""Segment Evaluation Pipeline CLI.

Parses Application Insights trace CSV exports and runs
Azure AI Foundry evaluation pipelines (custom + builtin
evaluators).

Three modes of operation
------------------------
1. csv-import : CSV → evaluation JSONL dataset
2. evaluate   : JSONL → Foundry eval pipeline (Part 4-7)
3. full       : csv-import + evaluate combined

Usage
-----
# 1. Parse CSV to evaluation dataset
python segment-eval-pipeline.py csv-import \
    --csv log/query_data_origin.csv \
    --output log/eval_dataset.jsonl

# 2. Run evaluation on existing dataset
python segment-eval-pipeline.py evaluate \
    --data log/eval_dataset.jsonl \
    --evaluators groundedness coherence relevance

# 3. Full pipeline (CSV → eval → dashboard)
python segment-eval-pipeline.py full \
    --csv log/query_data_origin.csv \
    --evaluators groundedness coherence relevance \
    --start "2026-03-09T14:00" \
    --end "2026-03-09T15:00"
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --------------- constants ---------------

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_DIR = SCRIPT_DIR / "log"
CONFIG_PATH = SCRIPT_DIR / ".." / "0_setup" / ".foundry_config.json"
ENV_PATH = SCRIPT_DIR / ".." / ".env"
MAX_CONTEXT_CHARS = 8_000

# Agent name → intent mapping (derived from production
# trace data where AGENT_NAME logs "agent.method").
AGENT_INTENT_MAP: Dict[str, Dict[str, str]] = {
    "productAgent": {
        "intent": "product_search",
        "method": "search_products",
    },
    "policyAgent": {
        "intent": "policy",
        "method": "search_policy",
    },
    "recommendAgent": {
        "intent": "recommendation",
        "method": "search_recsys",
    },
    "beautyAgent": {
        "intent": "beauty",
        "method": "search_beauty",
    },
}

# Evaluator catalogue – each entry describes one evaluator
# that the pipeline can register and run.
CUSTOM_EVALUATORS = {
    "intent_accuracy": {
        "pred": "predicted_intent",
        "exp": "expected_intent",
        "display": "Intent Accuracy",
        "desc": (
            "Exact-match: predicted vs expected intent."
        ),
    },
    "agent_relevance": {
        "pred": "predicted_agent",
        "exp": "expected_agent",
        "display": "Agent Relevance",
        "desc": (
            "Exact-match: predicted vs expected agent."
        ),
    },
    "method_relevance": {
        "pred": "predicted_method",
        "exp": "expected_method",
        "display": "Method Relevance",
        "desc": (
            "Exact-match: predicted vs expected method."
        ),
    },
}

BUILTIN_EVALUATORS = {
    "groundedness": {
        "evaluator_name": "builtin.groundedness",
        "data_mapping": {
            "query": "{{item.query}}",
            "response": "{{item.response}}",
            "context": "{{item.context}}",
        },
    },
    "coherence": {
        "evaluator_name": "builtin.coherence",
        "data_mapping": {
            "query": "{{item.query}}",
            "response": "{{item.response}}",
        },
    },
    "relevance": {
        "evaluator_name": "builtin.relevance",
        "data_mapping": {
            "query": "{{item.query}}",
            "response": "{{item.response}}",
            "context": "{{item.context}}",
        },
    },
}

ALL_EVALUATOR_NAMES = list(CUSTOM_EVALUATORS) + list(
    BUILTIN_EVALUATORS
)


# ============================================================
# Section 1 — CSV import
# ============================================================


def _parse_timestamp(raw: str) -> Optional[datetime]:
    """Parse Korean-locale App Insights timestamp.

    Format: "2026. 3. 9. 오후 2:09:17.674"

    Parameters:
    raw (str): Raw timestamp string from CSV.

    Returns:
    Optional[datetime]: Parsed datetime or None.
    """
    raw = raw.strip().strip('"')
    try:
        # Replace Korean AM/PM markers
        is_pm = "오후" in raw
        raw = raw.replace("오전", "").replace("오후", "")
        raw = raw.strip()
        # "2026. 3. 9.  2:09:17.674"
        dt = datetime.strptime(raw, "%Y. %m. %d. %H:%M:%S.%f")
        if is_pm and dt.hour < 12:
            dt = dt.replace(hour=dt.hour + 12)
        elif not is_pm and dt.hour == 12:
            dt = dt.replace(hour=0)
        return dt
    except ValueError:
        return None


def _parse_agent_name(
    agent_str: str,
) -> Tuple[str, str, str]:
    """Extract agent, method, and intent from AGENT_NAME.

    Parameters:
    agent_str (str): e.g. "productAgent.search_products"

    Returns:
    Tuple[str, str, str]: (agent, method, intent)
    """
    parts = agent_str.strip().split(".", 1)
    agent = parts[0] if parts else "unknown"
    method = parts[1] if len(parts) > 1 else "unknown"
    info = AGENT_INTENT_MAP.get(agent, {})
    intent = info.get("intent", "unknown")
    return agent, method, intent


def csv_import(
    csv_path: str,
    output_path: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Parse App Insights CSV export into evaluation JSONL.

    Groups trace rows by dd.trace_id, extracts key fields
    (USER_QUERY, AGENT_NAME, FINAL_ANSWER_RAW, context),
    and writes one JSONL record per conversation turn.

    Parameters:
    csv_path (str): Path to App Insights CSV export.
    output_path (str): Output JSONL file path.
    start (Optional[str]): ISO start time filter.
    end (Optional[str]): ISO end time filter.

    Returns:
    List[Dict[str, Any]]: Parsed evaluation records.
    """
    start_dt = (
        datetime.fromisoformat(start) if start else None
    )
    end_dt = (
        datetime.fromisoformat(end) if end else None
    )

    # Read CSV and group by trace_id
    traces: Dict[str, List[Dict[str, Any]]] = defaultdict(
        list
    )
    ts_col = None

    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        # Find timestamp column (may have BOM prefix)
        for col in reader.fieldnames or []:
            if "timestamp" in col.lower():
                ts_col = col
                break

        for row in reader:
            cd_raw = row.get("customDimensions", "")
            if not cd_raw:
                continue
            try:
                cd = json.loads(cd_raw)
            except json.JSONDecodeError:
                continue

            trace_id = cd.get("dd.trace_id")
            if not trace_id:
                continue

            # Time filter
            if ts_col and (start_dt or end_dt):
                ts = _parse_timestamp(row.get(ts_col, ""))
                if ts:
                    if start_dt and ts < start_dt:
                        continue
                    if end_dt and ts > end_dt:
                        continue

            traces[trace_id].append({
                "message": row.get("message", ""),
                "custom_type": cd.get("custom_type", ""),
                "session_id": cd.get("session_id", ""),
            })

    # Build evaluation records from traces
    records: List[Dict[str, Any]] = []
    for trace_id, events in traces.items():
        by_type: Dict[str, str] = {}
        for ev in events:
            ct = ev["custom_type"]
            # Keep first occurrence for each type
            if ct not in by_type:
                by_type[ct] = ev["message"]

        query = by_type.get("USER_QUERY", "")
        if not query:
            continue

        agent_raw = by_type.get("AGENT_NAME", "")
        agent, method, intent = _parse_agent_name(
            agent_raw
        )

        # Context: prefer AGENT_OUTPUT_FORMATTED, fallback
        # to AGENT_OUTPUT_RAW, then AGENT_OUTPUT
        context = (
            by_type.get("AGENT_OUTPUT_FORMATTED")
            or by_type.get("AGENT_OUTPUT_RAW")
            or by_type.get("AGENT_OUTPUT")
            or ""
        )

        response = by_type.get("FINAL_ANSWER_RAW", "")
        # Strip marker tags from response
        response = re.sub(
            r"\[!I[SE]-[A-Z-]+!\]", "", response
        ).strip()
        if response.startswith("message :"):
            response = response[len("message :"):].strip()

        records.append({
            "query": query,
            "expected_intent": intent,
            "expected_agent": agent,
            "expected_method": method,
            "predicted_intent": intent,
            "predicted_agent": agent,
            "predicted_method": method,
            "context": context[:MAX_CONTEXT_CHARS],
            "response": response,
            "ground_truth": "",
            "trace_id": trace_id,
        })

    # Write JSONL
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(
                json.dumps(rec, ensure_ascii=False) + "\n"
            )

    print(f"✅ Imported {len(records)} records")
    print(f"   from {csv_path}")
    print(f"   to   {output_path}")
    if start or end:
        print(
            f"   filter: {start or '*'} → {end or '*'}"
        )

    return records


# ============================================================
# Section 2 — Evaluation pipeline (Parts 4-7)
# ============================================================


def _load_config() -> Dict[str, Any]:
    """Load Foundry config and environment variables.

    Returns:
    Dict[str, Any]: Configuration dictionary.
    """
    from dotenv import load_dotenv

    load_dotenv(str(ENV_PATH), override=True)

    config_file = Path(CONFIG_PATH)
    if not config_file.exists():
        raise FileNotFoundError(
            f"Config not found: {config_file}\n"
            "Run 0_setup/1_setup.ipynb first."
        )
    with open(config_file, encoding="utf-8") as f:
        config = json.load(f)

    return {
        "endpoint": config["AZURE_AI_PROJECT_ENDPOINT"],
        "model": os.environ.get(
            "AZURE_OPENAI_CHAT_DEPLOYMENT_NAME",
            "gpt-4.1",
        ),
    }


def _exact_match_code(pred: str, exp: str) -> str:
    """Generate grade() source for exact-match evaluator.

    Parameters:
    pred (str): Predicted field name.
    exp (str): Expected field name.

    Returns:
    str: Python source code for PythonGrader.
    """
    return (
        "def grade(item, sample):\n"
        f"    p = (item.get('{pred}', '') or '')"
        ".strip().lower()\n"
        f"    e = (item.get('{exp}', '') or '')"
        ".strip().lower()\n"
        "    return 1.0 if p == e else 0.0\n"
    )


def _register_evaluators(
    project_client: Any,
    evaluator_names: List[str],
    eval_uuid: str,
) -> Dict[str, Any]:
    """Register custom code-based evaluators (Part 4).

    Skips builtin evaluators and already-registered ones.

    Parameters:
    project_client: AIProjectClient instance.
    evaluator_names (List[str]): Evaluators to register.
    eval_uuid (str): Unique suffix for evaluator names.

    Returns:
    Dict[str, Any]: Registered evaluator versions.
    """
    from azure.ai.projects.models import (
        CodeBasedEvaluatorDefinition,
        EvaluatorMetric,
        EvaluatorMetricDirection,
        EvaluatorMetricType,
        EvaluatorVersion,
    )

    metric = {
        "result": EvaluatorMetric(
            type=EvaluatorMetricType.ORDINAL,
            desirable_direction=(
                EvaluatorMetricDirection.INCREASE
            ),
            min_value=0.0,
            max_value=1.0,
        )
    }

    registered = {}
    for name in evaluator_names:
        if name not in CUSTOM_EVALUATORS:
            continue  # skip builtins
        spec = CUSTOM_EVALUATORS[name]
        full_name = f"{name}_{eval_uuid}"
        code = _exact_match_code(
            spec["pred"], spec["exp"]
        )
        ev = EvaluatorVersion(
            display_name=spec["display"],
            description=spec["desc"],
            definition=CodeBasedEvaluatorDefinition(
                code_text=code,
                data_schema={
                    "required": ["item"],
                    "type": "object",
                    "properties": {
                        "item": {
                            "type": "object",
                            "properties": {
                                spec["pred"]: {
                                    "type": "string"
                                },
                                spec["exp"]: {
                                    "type": "string"
                                },
                            },
                        },
                    },
                },
                metrics=metric,
            ),
        )
        reg = project_client.beta.evaluators.create_version(
            name=full_name, evaluator_version=ev,
        )
        registered[name] = reg
        print(f"   ✅ {name}: {reg.name} v{reg.version}")

    return registered


def _build_testing_criteria(
    evaluator_names: List[str],
    registered: Dict[str, Any],
    model: str,
) -> List[Dict[str, Any]]:
    """Build testing criteria for evals.create().

    Parameters:
    evaluator_names (List[str]): Evaluator list.
    registered (Dict[str, Any]): Registered custom evals.
    model (str): Model deployment name.

    Returns:
    List[Dict[str, Any]]: Testing criteria dicts.
    """
    criteria: List[Dict[str, Any]] = []

    for name in evaluator_names:
        if name in registered:
            spec = CUSTOM_EVALUATORS[name]
            criteria.append({
                "type": "azure_ai_evaluator",
                "name": name,
                "evaluator_name": registered[name].name,
                "pass_threshold": 0.5,
                "initialization_parameters": {
                    "pass_threshold": 0.5,
                },
                "data_mapping": {
                    spec["pred"]: (
                        f"{{{{item.{spec['pred']}}}}}"
                    ),
                    spec["exp"]: (
                        f"{{{{item.{spec['exp']}}}}}"
                    ),
                },
            })
        elif name in BUILTIN_EVALUATORS:
            bi = BUILTIN_EVALUATORS[name]
            criteria.append({
                "type": "azure_ai_evaluator",
                "name": name,
                "evaluator_name": bi["evaluator_name"],
                "pass_threshold": 0.5,
                "initialization_parameters": {
                    "deployment_name": model,
                },
                "data_mapping": bi["data_mapping"],
            })

    return criteria


def _run_eval(
    openai_client: Any,
    eval_records: List[Dict[str, Any]],
    testing_criteria: List[Dict[str, Any]],
    eval_uuid: str,
    model: str,
) -> Tuple[Any, Any, bool]:
    """Create eval + run via Evals API (Part 5).

    Parameters:
    openai_client: Foundry OpenAI client.
    eval_records (List[Dict]): Evaluation dataset.
    testing_criteria (List[Dict]): Testing criteria.
    eval_uuid (str): Unique run identifier.
    model (str): Model deployment name.

    Returns:
    Tuple[eval_obj, eval_run, foundry_mode]:
        Eval object, run object, and success flag.
    """
    from openai.types.eval_create_params import (
        DataSourceConfigCustom,
    )
    from openai.types.evals import (
        create_eval_jsonl_run_data_source_param as jp,
    )

    data_source_config = DataSourceConfigCustom(
        type="custom",
        item_schema={
            "type": "object",
            "properties": {
                k: {"type": "string"}
                for k in [
                    "query",
                    "expected_intent",
                    "predicted_intent",
                    "expected_agent",
                    "predicted_agent",
                    "expected_method",
                    "predicted_method",
                    "context",
                    "response",
                    "ground_truth",
                ]
            },
            "required": ["query"],
        },
    )

    eval_obj = openai_client.evals.create(
        name=f"Segment Eval {eval_uuid}",
        data_source_config=data_source_config,
        testing_criteria=testing_criteria,
    )
    print(f"   📝 Eval created: {eval_obj.id}")

    # Build JSONL upload
    upload_path = LOG_DIR / "eval_upload.jsonl"
    with open(upload_path, "w", encoding="utf-8") as f:
        for rec in eval_records:
            ctx = rec.get("context", "")
            if len(ctx) > MAX_CONTEXT_CHARS:
                ctx = ctx[:MAX_CONTEXT_CHARS]
            row = {"item": {
                k: rec.get(k, "")
                for k in [
                    "query",
                    "expected_intent",
                    "predicted_intent",
                    "expected_agent",
                    "predicted_agent",
                    "expected_method",
                    "predicted_method",
                    "response",
                    "ground_truth",
                ]
            }}
            row["item"]["context"] = ctx
            f.write(
                json.dumps(row, ensure_ascii=False) + "\n"
            )

    try:
        with open(upload_path, "rb") as f:
            uploaded = openai_client.files.create(
                file=f, purpose="evals"
            )
        print(f"   📤 File uploaded: {uploaded.id}")

        eval_run = openai_client.evals.runs.create(
            eval_id=eval_obj.id,
            name=f"Segment Run {eval_uuid}",
            metadata={
                "pipeline": "segment-eval",
                "model": model,
            },
            data_source=jp.CreateEvalJSONLRunDataSourceParam(
                type="jsonl",
                source=jp.SourceFileID(
                    type="file_id", id=uploaded.id,
                ),
            ),
        )
        print(f"   🚀 Eval run: {eval_run.id}")
        return eval_obj, eval_run, True

    except Exception as e:
        err = str(e)
        if "403" in err:
            print(
                "   ⚠️  403 on asset store — "
                "falling back to local mode."
            )
        else:
            print(f"   ⚠️  Run failed: {err[:120]}")
        return eval_obj, None, False


def _poll_and_collect(
    openai_client: Any,
    eval_obj: Any,
    eval_run: Any,
) -> Tuple[
    Dict[str, List[float]], List[Dict[str, Any]]
]:
    """Poll Foundry eval run and collect results (Part 6).

    Parameters:
    openai_client: Foundry OpenAI client.
    eval_obj: Eval object.
    eval_run: Eval run object.

    Returns:
    Tuple of (eval_summary, eval_rows).
    """
    print("   ⏳ Polling eval run...")
    while eval_run.status not in (
        "completed", "failed", "canceled",
    ):
        time.sleep(5)
        eval_run = openai_client.evals.runs.retrieve(
            run_id=eval_run.id,
            eval_id=eval_obj.id,
        )
        print(f"      Status: {eval_run.status}")

    summary: Dict[str, List[float]] = defaultdict(list)
    rows: List[Dict[str, Any]] = []

    if eval_run.status != "completed":
        print(f"   ❌ Eval {eval_run.status}")
        return summary, rows

    print("   ✅ Eval completed!")
    if eval_run.report_url:
        print(f"   📊 Report: {eval_run.report_url}")

    items = list(
        openai_client.evals.runs.output_items.list(
            run_id=eval_run.id,
            eval_id=eval_obj.id,
        )
    )

    for item in items:
        row: Dict[str, Any] = {}
        if hasattr(item, "datasource_item"):
            ds = item.datasource_item or {}
            row["query"] = ds.get("query", "")
        if hasattr(item, "results") and item.results:
            results = item.results
            if isinstance(results, list):
                for r in results:
                    name = getattr(
                        r, "name", None
                    ) or (
                        r.get("name")
                        if isinstance(r, dict)
                        else None
                    )
                    score = getattr(
                        r, "score", None
                    ) or (
                        r.get("score")
                        if isinstance(r, dict)
                        else None
                    )
                    if name and score is not None:
                        try:
                            score = float(score)
                        except (ValueError, TypeError):
                            continue
                        summary[name].append(score)
                        row[name] = score
            elif isinstance(results, dict):
                for name, res in results.items():
                    score = (
                        getattr(res, "score", None)
                        if hasattr(res, "score")
                        else res.get("score")
                        if isinstance(res, dict)
                        else None
                    )
                    if score is not None:
                        try:
                            score = float(score)
                        except (ValueError, TypeError):
                            continue
                        summary[name].append(score)
                        row[name] = score
        rows.append(row)

    return summary, rows


def _local_eval(
    openai_client: Any,
    eval_records: List[Dict[str, Any]],
    evaluator_names: List[str],
    model: str,
) -> Tuple[
    Dict[str, List[float]], List[Dict[str, Any]]
]:
    """Run evaluation locally as fallback (Part 6 local).

    Parameters:
    openai_client: Foundry OpenAI client.
    eval_records (List[Dict]): Dataset records.
    evaluator_names (List[str]): Evaluators to run.
    model (str): Model deployment name.

    Returns:
    Tuple of (eval_summary, eval_rows).
    """
    print("   🔄 Running local evaluation...")
    summary: Dict[str, List[float]] = defaultdict(list)
    rows: List[Dict[str, Any]] = []

    prompt_tpl = (
        "You are an evaluation judge. "
        "Score the response on **{metric}** (1-5).\n\n"
        "### Query\n{query}\n\n"
        "{ctx}"
        "### Response\n{response}\n\n"
        'Return JSON only: {{"score": <1-5>, '
        '"reason": "<brief>"}}'
    )

    def _llm_score(
        query: str, response: str,
        context: str, metric: str,
    ) -> float:
        ctx = (
            f"### Context\n{context[:3000]}\n\n"
            if context else ""
        )
        prompt = prompt_tpl.format(
            metric=metric, query=query,
            ctx=ctx, response=response[:2000],
        )
        try:
            result = openai_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=150,
            )
            text = (
                result.choices[0].message.content or ""
            )
            m = re.search(r'"score"\s*:\s*(\d+)', text)
            if m:
                return min(int(m.group(1)), 5) / 5.0
        except Exception as exc:
            print(f"      ⚠️ {metric}: {str(exc)[:60]}")
        return 0.0

    def _exact(pred: str, exp: str) -> float:
        p = (pred or "").strip().lower()
        e = (exp or "").strip().lower()
        return 1.0 if p == e else 0.0

    for i, rec in enumerate(eval_records):
        row: Dict[str, Any] = {"query": rec["query"]}
        for name in evaluator_names:
            if name in CUSTOM_EVALUATORS:
                spec = CUSTOM_EVALUATORS[name]
                row[name] = _exact(
                    rec.get(spec["pred"], ""),
                    rec.get(spec["exp"], ""),
                )
            elif name in BUILTIN_EVALUATORS:
                row[name] = _llm_score(
                    rec["query"],
                    rec.get("response", ""),
                    rec.get("context", ""),
                    name,
                )
            summary[name].append(row.get(name, 0.0))
        rows.append(row)
        n = len(eval_records)
        print(f"      [{i+1}/{n}] done")

    print(f"   ✅ Local eval: {len(rows)} rows")
    return summary, rows


# ============================================================
# Section 3 — Dashboard (Part 7)
# ============================================================


def _score_color(score: float) -> str:
    """Return CSS color based on score value."""
    if score >= 0.8:
        return "#22c55e"
    if score >= 0.5:
        return "#eab308"
    return "#ef4444"


def generate_dashboard(
    summary_payload: Dict[str, Any],
    rows: List[Dict[str, Any]],
    output_path: str,
    model: str,
) -> str:
    """Generate HTML dashboard (Part 7).

    Parameters:
    summary_payload (Dict): Aggregated metrics.
    rows (List[Dict]): Per-row results.
    output_path (str): Output HTML path.
    model (str): Model deployment name.

    Returns:
    str: Path to generated dashboard.
    """
    metrics = summary_payload.get("metrics", {})
    eval_id = summary_payload.get("eval_id", "N/A")
    run_id = summary_payload.get("run_id", "N/A")
    ts = summary_payload.get("timestamp", "")
    report_url = summary_payload.get("report_url", "")

    cards = ""
    for name, info in metrics.items():
        avg = info["avg"]
        color = _score_color(avg)
        cards += (
            f'<div class="card">'
            f'<div class="card-title">{name}</div>'
            f'<div class="card-score" '
            f'style="color:{color}">{avg:.3f}</div>'
            f'<div class="card-sub">'
            f'n={info["count"]}</div></div>'
        )

    hdr = "".join(
        f"<th>{n}</th>" for n in metrics
    )
    trows = ""
    for i, row in enumerate(rows, 1):
        q = row.get("query", "")[:80]
        cells = f"<td>{i}</td><td>{q}</td>"
        for name in metrics:
            val = row.get(name)
            if val is not None:
                color = _score_color(val)
                icon = "✅" if val >= 0.5 else "❌"
                cells += (
                    f'<td style="color:{color}">'
                    f"{icon} {val:.2f}</td>"
                )
            else:
                cells += "<td>—</td>"
        trows += f"<tr>{cells}</tr>\n"

    portal = ""
    if report_url:
        portal = (
            f'<a href="{report_url}" target="_blank"'
            f' class="portal-link">'
            f"Open in Foundry Portal →</a>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Segment Evaluation Dashboard</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,
'Segoe UI',Roboto,sans-serif;background:#0f172a;
color:#e2e8f0;padding:2rem}}
.header{{text-align:center;margin-bottom:2rem;
border-bottom:1px solid #334155;padding-bottom:1rem}}
.header h1{{color:#60a5fa;font-size:1.8rem}}
.header .meta{{color:#94a3b8;font-size:.85rem;
margin-top:.5rem}}
.portal-link{{display:inline-block;margin-top:1rem;
padding:.5rem 1.5rem;background:#2563eb;color:#fff;
text-decoration:none;border-radius:6px;font-weight:600}}
.cards{{display:flex;gap:1rem;flex-wrap:wrap;
justify-content:center;margin:2rem 0}}
.card{{background:#1e293b;border-radius:12px;
padding:1.5rem 2rem;min-width:160px;text-align:center;
border:1px solid #334155}}
.card-title{{color:#94a3b8;font-size:.8rem;
text-transform:uppercase;letter-spacing:.05em}}
.card-score{{font-size:2rem;font-weight:700;
margin:.5rem 0}}
.card-sub{{color:#64748b;font-size:.75rem}}
table{{width:100%;border-collapse:collapse;
margin-top:1rem;font-size:.85rem}}
th{{background:#1e293b;color:#94a3b8;padding:.75rem;
text-align:left;border-bottom:2px solid #334155;
text-transform:uppercase;font-size:.75rem}}
td{{padding:.6rem .75rem;
border-bottom:1px solid #1e293b}}
tr:hover{{background:#1e293b}}
.section-title{{color:#60a5fa;font-size:1.2rem;
margin:2rem 0 1rem;font-weight:600}}
</style></head><body>
<div class="header"><h1>Segment Evaluation Dashboard</h1>
<div class="meta">Eval: {eval_id} | Run: {run_id} |
Model: {model} | {ts}</div>{portal}</div>
<div class="cards">{cards}</div>
<div class="section-title">Per-Row Results</div>
<table><thead><tr><th>#</th><th>Query</th>
{hdr}</tr></thead><tbody>{trows}</tbody></table>
</body></html>"""

    Path(output_path).parent.mkdir(
        parents=True, exist_ok=True
    )
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"   📄 Dashboard: {output_path}")
    return output_path


# ============================================================
# Section 4 — Orchestrator
# ============================================================


def run_evaluate(
    data_path: str,
    evaluator_names: List[str],
    dashboard_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the full evaluation pipeline (Parts 4-7).

    Parameters:
    data_path (str): Path to evaluation JSONL.
    evaluator_names (List[str]): Evaluators to run.
    dashboard_path (Optional[str]): Dashboard output.

    Returns:
    Dict[str, Any]: Evaluation summary payload.
    """
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    cfg = _load_config()
    eval_uuid = datetime.now().strftime("%Y%m%d%H%M%S")
    model = cfg["model"]

    # Load records
    records: List[Dict[str, Any]] = []
    with open(data_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line.strip()))
    print(f"📊 Loaded {len(records)} records")

    # Validate evaluator names
    valid = [
        e for e in evaluator_names
        if e in ALL_EVALUATOR_NAMES
    ]
    invalid = set(evaluator_names) - set(valid)
    if invalid:
        print(
            f"⚠️  Unknown evaluators: {invalid}. "
            f"Available: {ALL_EVALUATOR_NAMES}"
        )
    if not valid:
        print("❌ No valid evaluators specified.")
        sys.exit(1)

    print(
        f"📋 Evaluators: {valid}"
    )

    # Initialize clients
    credential = DefaultAzureCredential()
    project_client = AIProjectClient(
        endpoint=cfg["endpoint"],
        credential=credential,
    )
    openai_client = project_client.get_openai_client()

    # Part 4: Register custom evaluators
    print("\n── Part 4: Register Evaluators ──")
    registered = _register_evaluators(
        project_client, valid, eval_uuid,
    )
    custom_count = len(registered)
    builtin_count = sum(
        1 for e in valid if e in BUILTIN_EVALUATORS
    )
    print(
        f"   {custom_count} custom + "
        f"{builtin_count} builtin"
    )

    # Build testing criteria
    criteria = _build_testing_criteria(
        valid, registered, model,
    )

    # Part 5: Run evaluation
    print("\n── Part 5: Run Evaluation ──")
    eval_obj, eval_run, foundry_mode = _run_eval(
        openai_client, records, criteria,
        eval_uuid, model,
    )

    # Part 6: Collect results
    print("\n── Part 6: Collect Results ──")
    if foundry_mode and eval_run:
        summary, rows = _poll_and_collect(
            openai_client, eval_obj, eval_run,
        )
    else:
        summary, rows = _local_eval(
            openai_client, records, valid, model,
        )

    # Print summary
    print("\n" + "=" * 55)
    print("📊 Evaluation Summary")
    print("=" * 55)
    for name, scores in summary.items():
        avg = (
            sum(scores) / len(scores) if scores else 0.0
        )
        print(
            f"   {name:25s} │ "
            f"avg={avg:.3f}  n={len(scores)}"
        )
    print(f"   Total rows: {len(rows)}")

    # Build summary payload
    payload = {
        "eval_id": eval_obj.id,
        "run_id": (
            eval_run.id if eval_run else None
        ),
        "status": (
            eval_run.status
            if eval_run else "local_completed"
        ),
        "report_url": (
            getattr(eval_run, "report_url", None)
            if eval_run else None
        ),
        "mode": (
            "foundry" if foundry_mode else "local"
        ),
        "model": model,
        "metrics": {
            k: {
                "avg": (
                    sum(v) / len(v) if v else 0.0
                ),
                "count": len(v),
            }
            for k, v in summary.items()
        },
        "timestamp": eval_uuid,
        "total_rows": len(rows),
    }

    # Save summary JSON
    summary_path = LOG_DIR / "eval_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n💾 Summary: {summary_path}")

    # Part 7: Dashboard
    print("\n── Part 7: Dashboard ──")
    dash = dashboard_path or str(
        LOG_DIR / "eval_dashboard.html"
    )
    generate_dashboard(payload, rows, dash, model)

    return payload


# ============================================================
# Section 5 — CLI
# ============================================================


def _build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser.

    Returns:
    argparse.ArgumentParser: Configured parser.
    """
    parser = argparse.ArgumentParser(
        prog="segment-eval-pipeline",
        description=(
            "Evaluate Application Insights traces "
            "using Azure AI Foundry Evals API."
        ),
    )
    sub = parser.add_subparsers(dest="command")

    # --- csv-import ---
    p_csv = sub.add_parser(
        "csv-import",
        help="Parse App Insights CSV → eval JSONL",
    )
    p_csv.add_argument(
        "--csv", required=True,
        help="Path to App Insights CSV export",
    )
    p_csv.add_argument(
        "--output", default=str(
            LOG_DIR / "eval_dataset.jsonl"
        ),
        help="Output JSONL path",
    )
    p_csv.add_argument(
        "--start", default=None,
        help="Start time filter (ISO format)",
    )
    p_csv.add_argument(
        "--end", default=None,
        help="End time filter (ISO format)",
    )

    # --- evaluate ---
    p_eval = sub.add_parser(
        "evaluate",
        help="Run eval pipeline (Part 4-7)",
    )
    p_eval.add_argument(
        "--data", required=True,
        help="Path to evaluation JSONL dataset",
    )
    p_eval.add_argument(
        "--evaluators", nargs="+",
        default=["groundedness", "coherence", "relevance"],
        help=(
            f"Evaluators to run: "
            f"{ALL_EVALUATOR_NAMES}"
        ),
    )
    p_eval.add_argument(
        "--dashboard", default=None,
        help="Output HTML dashboard path",
    )

    # --- full ---
    p_full = sub.add_parser(
        "full",
        help="CSV → eval → dashboard (combined)",
    )
    p_full.add_argument(
        "--csv", required=True,
        help="Path to App Insights CSV export",
    )
    p_full.add_argument(
        "--evaluators", nargs="+",
        default=["groundedness", "coherence", "relevance"],
        help=(
            f"Evaluators to run: "
            f"{ALL_EVALUATOR_NAMES}"
        ),
    )
    p_full.add_argument(
        "--start", default=None,
        help="Start time filter (ISO format)",
    )
    p_full.add_argument(
        "--end", default=None,
        help="End time filter (ISO format)",
    )
    p_full.add_argument(
        "--output", default=str(
            LOG_DIR / "eval_dataset.jsonl"
        ),
        help="Intermediate JSONL output path",
    )
    p_full.add_argument(
        "--dashboard", default=None,
        help="Output HTML dashboard path",
    )

    return parser


def main() -> None:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "csv-import":
        csv_import(
            args.csv, args.output,
            args.start, args.end,
        )

    elif args.command == "evaluate":
        run_evaluate(
            args.data, args.evaluators,
            args.dashboard,
        )

    elif args.command == "full":
        print("═" * 55)
        print("Phase 1: CSV Import")
        print("═" * 55)
        csv_import(
            args.csv, args.output,
            args.start, args.end,
        )
        print()
        print("═" * 55)
        print("Phase 2: Evaluation Pipeline")
        print("═" * 55)
        run_evaluate(
            args.output, args.evaluators,
            args.dashboard,
        )


if __name__ == "__main__":
    main()
