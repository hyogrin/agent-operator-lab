"""Application settings loaded from environment variables."""

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


# Default paths relative to this package
_PACKAGE_DIR = Path(__file__).resolve().parent
_OBS_DIR = _PACKAGE_DIR.parent.parent  # 4_observability/


class Settings(BaseSettings):
    """
    Configuration for the SK Orchestrator backend.

    Values are loaded from environment variables or a .env file
    located in the repository root.

    Parameters:
    azure_openai_endpoint (str): Azure OpenAI endpoint URL.
    azure_openai_api_key (str): Azure OpenAI API key.
    azure_openai_chat_deployment_name (str): Model deployment.
    azure_openai_api_version (str): API version.
    applicationinsights_connection_string (str): App Insights.
    product_contexts_path (str): Path to product XML.
    recommendation_contexts_path (str): Path to recommendation XML.
    """

    azure_openai_endpoint: str = Field(
        default="",
        description="Azure OpenAI endpoint URL",
    )
    azure_openai_api_key: str = Field(
        default="",
        description="Azure OpenAI API key",
    )
    azure_openai_chat_deployment_name: str = Field(
        default="gpt-4.1",
        description="Chat model deployment name",
    )
    azure_openai_api_version: str = Field(
        default="2025-03-01-preview",
        description="Azure OpenAI API version",
    )
    applicationinsights_connection_string: str = Field(
        default="",
        description="Application Insights connection string",
    )
    product_contexts_path: str = Field(
        default=str(_OBS_DIR / "contexts" / "product_contexts.xml"),
        description="Path to product_contexts.xml",
    )
    recommendation_contexts_path: str = Field(
        default=str(
            _OBS_DIR / "contexts" / "recommendation_contexts.xml"
        ),
        description="Path to recommendation_contexts.xml",
    )
    service_name: str = Field(
        default="sk-orchestrator-backend",
        description="OpenTelemetry service name",
    )
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, description="Server port")

    model_config = {"env_file": str(
        Path(os.environ.get("ENV_FILE", ""))
        if os.environ.get("ENV_FILE")
        else _OBS_DIR.parent / ".env"
    ), "extra": "ignore"}
