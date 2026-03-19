"""
FastAPI application for the SK Orchestrator backend.

Exposes ``/chat``, ``/classify``, and ``/health`` endpoints.
"""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from azure.monitor.opentelemetry import configure_azure_monitor
from fastapi import FastAPI, HTTPException
from opentelemetry import trace

from sk_orchestrator.config import Settings
from sk_orchestrator.models import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    IntentResult,
)
from sk_orchestrator.orchestrator import SKOrchestrator

# Module-level references populated during lifespan
_orchestrator: SKOrchestrator | None = None
_settings: Settings | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Initialise settings, telemetry, and orchestrator on startup.

    OTEL env vars are set before configure_azure_monitor() and
    kernel creation to ensure SK captures all diagnostic spans.
    On shutdown, the tracer provider is flushed so pending spans
    are exported before the process exits.
    """
    global _orchestrator, _settings

    _settings = Settings()

    # 1. Set SK OTEL env vars FIRST — must be present before
    #    any Semantic Kernel service is instantiated.
    os.environ[
        "SEMANTICKERNEL_EXPERIMENTAL_GENAI_ENABLE_"
        "OTEL_DIAGNOSTICS"
    ] = "true"
    os.environ[
        "SEMANTICKERNEL_EXPERIMENTAL_GENAI_ENABLE_"
        "OTEL_DIAGNOSTICS_SENSITIVE"
    ] = "true"

    # Set OTEL service name so cloud_RoleName is populated
    os.environ["OTEL_SERVICE_NAME"] = _settings.service_name

    # 2. Configure Azure Monitor exporter
    conn_str = _settings.applicationinsights_connection_string
    if conn_str:
        configure_azure_monitor(
            connection_string=conn_str,
            enable_live_metrics=True,
        )

    # 3. Create tracer and orchestrator (after OTEL is configured)
    tracer = trace.get_tracer(
        _settings.service_name, "1.0.0"
    )
    _orchestrator = SKOrchestrator(_settings, tracer=tracer)

    yield  # app is running

    # 4. Flush pending telemetry before shutdown
    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush(timeout_millis=5000)

    _orchestrator = None
    _settings = None


app = FastAPI(
    title="SK Orchestrator Backend",
    description=(
        "Semantic Kernel + FastAPI chatbot backend that "
        "classifies intent and generates XML-grounded answers "
        "for a Korean beauty/cosmetics application."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


# ---- endpoints ------------------------------------------------


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """
    Run the full pipeline: intent → XML context → LLM answer.

    Parameters:
    req (ChatRequest): Incoming chat request with ``query``.

    Returns:
    ChatResponse: Pipeline result including answer and metadata.
    """
    if _orchestrator is None:
        raise HTTPException(
            status_code=503,
            detail="Orchestrator not initialised",
        )

    result = await _orchestrator.run(req.query)
    return ChatResponse(**result)


@app.post("/classify", response_model=IntentResult)
async def classify(req: ChatRequest) -> IntentResult:
    """
    Classify intent only (no answer generation).

    Parameters:
    req (ChatRequest): Incoming chat request with ``query``.

    Returns:
    IntentResult: Classified intent with confidence and reasoning.
    """
    if _orchestrator is None:
        raise HTTPException(
            status_code=503,
            detail="Orchestrator not initialised",
        )

    return await _orchestrator.classify_intent(req.query)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """
    Health check endpoint.

    Returns:
    HealthResponse: Service status and model info.
    """
    model = (
        _settings.azure_openai_chat_deployment_name
        if _settings
        else "unknown"
    )
    return HealthResponse(
        status="healthy",
        service="sk-orchestrator-backend",
        model=model,
    )


# ---- CLI entry point ------------------------------------------


def run() -> None:
    """Start the uvicorn server (used by ``sk-orchestrator`` CLI)."""
    import uvicorn

    settings = Settings()
    uvicorn.run(
        "sk_orchestrator.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
