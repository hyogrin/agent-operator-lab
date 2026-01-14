---
post_title: "Hosted agent container: build and push to ACR"
author1: "GitHub Copilot"
post_slug: "hosted-agent-acr"
microsoft_alias: "n/a"
featured_image: ""
categories: []
tags:
  - azure
  - ai-foundry
  - hosted-agents
  - acr
  - docker
ai_note: "Created with AI assistance."
summary: "Build a Docker image for a Foundry hosted agent and push it to Azure Container Registry (ACR)."
post_date: "2026-01-07"
---

## Overview
This folder contains a minimal Python hosted agent packaged as a Docker container.
Microsoft Foundry hosted agents are deployed from container images stored in Azure Container Registry (ACR).

Reference: [What are hosted agents? (Build and push your Docker image to Azure Container Registry)](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/concepts/hosted-agents?view=foundry&tabs=foundry-sdk#build-and-push-your-docker-image-to-azure-container-registry)

## Prerequisites
- Docker installed and running.
- Azure CLI (`az`) installed and signed in.
- An existing Azure Container Registry.

## Build and push your image to ACR

### 0) Update az cli (if needed)
```bash
az upgrade
```

### 1) Build the image locally
From this directory:

```bash
docker build -t hostedagent:1 .
```

### 2) Create an Azure Container Registry (if needed)
If you don't have an ACR, create one:

```bash
az acr create --name <myregistry> --resource-group <my-rg> --sku Basic
```

### 3) Sign in to Azure Container Registry
```bash
az acr login --name <myregistry>
```

### 4) Tag the image for your registry
```bash
docker tag hostedagent:1 <myregistry>.azurecr.io/hostedagent:1
```

### 5) Push the image
```bash
docker push <myregistry>.azurecr.io/hostedagent:1
```

## Check your Managed Identity of Foundry Account has ACR pull permission
To allow your Foundry hosted agent to pull the image from ACR, ensure the following steps are completed:

### 1) Verify Foundry Account's Managed Identity
In the Azure Portal, navigate to your Foundry resource (not project) and find the Managed Identity section to get the identity details.
```bash
az cognitiveservices account identity show \
  --name <myfoundryresource> \
  --resource-group <my-rg> \
  --query principalId -o tsv
```

### 2) Grant ACR pull permission
Assign the **Container Registry Repository Reader** role to the Foundry project's managed identity on your ACR.
```bash
# Foundry의 Managed Identity에 ACR pull 권한 부여
az role assignment create \
  --assignee <foundry-managed-identity-principal-id> \
  --role "AcrPull" \
  --scope /subscriptions/<my-subscription-id>/resourceGroups/<my-rg>/providers/Microsoft.ContainerRegistry/registries/<myregistry>
```

### 3) Inside the Hosted Agent container
When the hosted agent runs on the Capability Host:
- Azure automatically injects the Foundry's Managed Identity into the container.
- `DefaultAzureCredential()` automatically detects and uses it.



## Notes
- Your Foundry project (managed identity) must be granted permission to pull the image from ACR.
  In Azure Portal, assign the **Container Registry Repository Reader** role on the registry to the
  project’s system-assigned managed identity.