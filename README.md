## Agent Operator Lab

This repo contains hands-on notebooks and sample agents for operating and connecting agents in **Azure AI Foundry** from a **Control Plane** perspective.
The focus is practical: create (or point to) a Foundry project, run lightweight inventory/monitoring checks, and connect both **MS Agent Framework** agents and **Hosted Agents**.

## What’s Included

- [0_setup/1_setup.ipynb](0_setup/1_setup.ipynb): Bootstrap the minimum Foundry resources (Resource Group, AIServices account, Project), discover the Project endpoint/API key, and write a local config file for reuse.
- [1_controlplane/1_foundry_agent_monitoring.ipynb](1_controlplane/1_foundry_agent_monitoring.ipynb): Control Plane checks with the Foundry SDK (list deployed agents, inspect assets like connections, and understand where quota is managed).
- [1_controlplane/2_ms_agent_framework_connect_foundry.ipynb](1_controlplane/2_ms_agent_framework_connect_foundry.ipynb): Connect **MS Agent Framework** agents using `AzureAIClient`, including conversation/thread linkage and tracing verification in the Foundry portal.
- [1_controlplane/3_hosted_agent_connect_foundry.ipynb](1_controlplane/3_hosted_agent_connect_foundry.ipynb): Package agents as containers, push to ACR, and register **Hosted Agents** using the Hosting Adapter (with sample agents under `1_controlplane/1.1_hosted-agent_sdk/`).
- [1_controlplane/4_agent_fleet_management.ipynb](1_controlplane/4_agent_fleet_management.ipynb): Batch registration of agents/workflows and real-time simulation with live metrics tracking in Azure AI Foundry.
- [2_workload_optimization/1_context_optimization.ipynb](2_workload_optimization/1_context_optimization.ipynb): Context optimization strategies using MCP and code execution—comparing anti-patterns vs best practices for efficient token usage.
- [2_workload_optimization/2_new_model_comparison.ipynb](2_workload_optimization/2_new_model_comparison.ipynb): Model comparison and benchmarking (latency, token usage, cost efficiency, accuracy) with the Azure OpenAI Responses API.
- [2_workload_optimization/3_model_migration.ipynb](2_workload_optimization/3_model_migration.ipynb): Model migration workflow (e.g., GPT-4.x → GPT-5.x) with APIM weighted routing (canary rollout) and acceptance criteria analysis.

## Prerequisites

- Python 3.12+
- Azure CLI (`az`) and an Azure account with access to Azure AI Foundry
- For Hosted Agents: Docker and an Azure Container Registry (ACR)

## Setup

```bash
uv sync --prerelease=allow
source .venv/bin/activate
```

Copy environment variables:

```bash
cp sample.env .env
```

Update `.env` values as needed. Common variables used across the notebooks:

- `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`
- `AZURE_AI_MODEL_DEPLOYMENT_NAME` (model deployment name in Foundry)
- `AZURE_OPENAI_ENDPOINT` (Azure OpenAI endpoint)
- `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME` (used by some notebooks/samples)
- `AZURE_CONTAINER_REGISTRY` (required for Hosted Agent container builds)
- `BING_GROUNDING_CONNECTION_NAME` (only if you run the web-search hosted agent scenario)

Note: authentication is typically done via `DefaultAzureCredential` (e.g., `az login`). Some flows may also use `AZURE_OPENAI_API_KEY` depending on the notebook/sample.

## Suggested Run Order

1. Run [0_setup/1_setup.ipynb](0_setup/1_setup.ipynb) to create or configure your Foundry Project.
2. Run [1_controlplane/1_foundry_agent_monitoring.ipynb](1_controlplane/1_foundry_agent_monitoring.ipynb) for basic fleet/assets checks.
3. Run [1_controlplane/2_ms_agent_framework_connect_foundry.ipynb](1_controlplane/2_ms_agent_framework_connect_foundry.ipynb) to connect MS Agent Framework agents and verify tracing.
4. Run [1_controlplane/3_hosted_agent_connect_foundry.ipynb](1_controlplane/3_hosted_agent_connect_foundry.ipynb) to build/push container images and register Hosted Agents.
5. Run [1_controlplane/4_agent_fleet_management.ipynb](1_controlplane/4_agent_fleet_management.ipynb) to batch-register agents/workflows and run real-time simulations.
6. Run [2_workload_optimization/1_context_optimization.ipynb](2_workload_optimization/1_context_optimization.ipynb) to learn context optimization patterns with MCP.
7. Run [2_workload_optimization/2_new_model_comparison.ipynb](2_workload_optimization/2_new_model_comparison.ipynb) to benchmark and compare models.
8. Run [2_workload_optimization/3_model_migration.ipynb](2_workload_optimization/3_model_migration.ipynb) to practice weighted routing for model migration.

## Hosted Agent Samples

Sample agents live under `1_controlplane/1.1_hosted-agent_sdk/`:

- `calculator-agent`: LangGraph + Hosting Adapter (simple arithmetic tools)
- `msft-docs-agent`: MAF-based example
- `workflow-agent`: concurrent workflow example
- `web-search-agent`: grounding with Bing Search connection

## Security Notes

- Do not commit `.env` or `0_setup/.foundry_config.json` (they can contain secrets like API keys).
- If a key was ever committed, rotate the key in Azure and rewrite Git history before sharing the repo.

