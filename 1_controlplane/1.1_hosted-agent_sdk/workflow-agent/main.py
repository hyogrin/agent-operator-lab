# Copyright (c) Microsoft. All rights reserved.
import os
from dotenv import load_dotenv
load_dotenv()
from agent_framework import ConcurrentBuilder
from agent_framework.azure import AzureOpenAIChatClient
from azure.ai.agentserver.agentframework import from_agent_framework
from azure.identity import DefaultAzureCredential, ClientSecretCredential  # pyright: ignore[reportUnknownVariableType]



#def get_token_provider(credential):
 #   """Create an async token provider function for Azure OpenAI."""
 #   from azure.identity import get_bearer_token_provider
 #   return get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default")


def create_agent():
    credential = DefaultAzureCredential()
    #token_provider = get_token_provider(credential)
    
    # Create agents
    researcher = AzureOpenAIChatClient(credential=credential).create_agent(
        instructions=(
            "You're an expert market and product researcher. "
            "Given a prompt, provide concise, factual insights, opportunities, and risks. Provide numbers driven examples when relevant"
        ),
        name="researcher",
    )
    marketer = AzureOpenAIChatClient(credential=credential).create_agent(
        instructions=(
            "You're a creative marketing strategist. "
            "Craft compelling value propositions and target messaging aligned to the prompt."
        ),
        name="marketer",
    )
    legal = AzureOpenAIChatClient(credential=credential).create_agent(
        instructions=(
            "You're a cautious legal/compliance reviewer. "
            "Highlight constraints, disclaimers, and policy concerns based on the prompt."
        ),
        name="legal",
    )

    # Build a concurrent workflow
    workflow = ConcurrentBuilder().participants([researcher, marketer, legal]).build()

    # Convert the workflow to an agent
    workflow_agent = workflow.as_agent()

    return workflow_agent

def main():
    # Run the agent as a hosted agent
    from_agent_framework(lambda _: create_agent()).run()


if __name__ == "__main__":
    main()