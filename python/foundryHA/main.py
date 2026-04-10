# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Work IQ Foundry Hosted Agent — main entry point.

A Foundry Hosted Agent that wraps the Work IQ A2A client as a local tool,
enabling multi-turn conversations with Work IQ through the Foundry Agent Service.
Uses Microsoft Agent Framework with Azure AI Foundry.
"""

import asyncio
import logging
import os

from dotenv import load_dotenv

load_dotenv(override=True)

from agent_framework import Agent
from agent_framework.azure import AzureAIAgentClient
from azure.ai.agentserver.agentframework import from_agent_framework
from azure.identity.aio import DefaultAzureCredential

from workiq_tool import send_to_workiq_agent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Configure these for your Foundry project
PROJECT_ENDPOINT = os.getenv("PROJECT_ENDPOINT")
MODEL_DEPLOYMENT_NAME = os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini")


async def main():
    """Main function to run the agent as a web server."""
    async with (
        DefaultAzureCredential() as credential,
        AzureAIAgentClient(
            project_endpoint=PROJECT_ENDPOINT,
            model_deployment_name=MODEL_DEPLOYMENT_NAME,
            credential=credential,
        ) as client,
    ):
        agent = Agent(
            client,
            name="WorkIQAgent",
            instructions="""You are a helpful assistant that connects users to Microsoft Work IQ.

When a user asks a question or makes a request:
1. Use the send_to_workiq_agent tool to forward their message to the Work IQ agent.
2. Return the Work IQ agent's response to the user, preserving any formatting and citations.
3. If the response includes sources/citations, present them clearly.
4. If Work IQ returns an error, let the user know and suggest they try rephrasing their question.

You support multi-turn conversations — context is automatically maintained across messages.
Be conversational and helpful. Pass through the user's intent faithfully to Work IQ.""",
            tools=[send_to_workiq_agent],
        )

        logger.info("Work IQ Agent Server running on http://localhost:8088")
        server = from_agent_framework(agent)
        await server.run_async()


if __name__ == "__main__":
    asyncio.run(main())
