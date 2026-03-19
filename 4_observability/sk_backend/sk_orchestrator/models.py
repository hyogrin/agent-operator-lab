"""Pydantic models and enums for the SK Orchestrator."""

from enum import Enum
from typing import Dict

from pydantic import BaseModel, Field


class IntentType(str, Enum):
    """
    Intent types derived from Application Insights logs.

    Each value maps to a specific agent and method in the
    INTENT_AGENT_MAP used for evaluation ground truth.
    """

    PRODUCT_SEARCH = "product_search"
    RECOMMENDATION = "recommendation"
    POLICY = "policy"
    BEAUTY = "beauty"
    UNKNOWN = "unknown"


class IntentResult(BaseModel):
    """
    Structured output for intent classification.

    Parameters:
    intent (IntentType): Classified intent type.
    confidence (float): Confidence score between 0 and 1.
    reasoning (str): Brief explanation for classification.
    """

    intent: IntentType = Field(
        description="Classified intent type",
    )
    confidence: float = Field(
        description="Confidence score between 0 and 1",
        ge=0.0,
        le=1.0,
    )
    reasoning: str = Field(
        description="Brief explanation for classification",
    )


# Mapping: intent → expected agent and method (ground truth)
INTENT_AGENT_MAP: Dict[str, Dict[str, str]] = {
    "product_search": {
        "agent": "productAgent",
        "method": "search_products",
    },
    "recommendation": {
        "agent": "recommendAgent",
        "method": "search_recsys",
    },
    "policy": {
        "agent": "policyAgent",
        "method": "search_policy",
    },
    "beauty": {
        "agent": "beautyAgent",
        "method": "search_beauty",
    },
}


# --- API request / response schemas ---


class ChatRequest(BaseModel):
    """
    Incoming chat request.

    Parameters:
    query (str): User query text.
    session_id (str): Optional session identifier.
    """

    query: str = Field(description="User query text")
    session_id: str = Field(
        default="",
        description="Optional session identifier",
    )


class ChatResponse(BaseModel):
    """
    Chat pipeline response.

    Parameters:
    query (str): Original user query.
    intent (str): Classified intent type.
    confidence (float): Intent confidence score.
    agent (str): Matched agent name.
    method (str): Matched agent method.
    context_source (str): XML context file used.
    answer (str): LLM-generated answer.
    """

    query: str
    intent: str
    confidence: float
    agent: str
    method: str
    context_source: str
    answer: str


class HealthResponse(BaseModel):
    """
    Health check response.

    Parameters:
    status (str): Service status.
    service (str): Service name.
    model (str): Deployed model name.
    """

    status: str
    service: str
    model: str
