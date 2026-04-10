# Work IQ — Foundry Hosted Agent

A [Foundry Hosted Agent](https://learn.microsoft.com/azure/ai-foundry/agents/concepts/hosted-agents) that wraps the Work IQ A2A (Agent-to-Agent) client as a tool, enabling multi-turn conversations with Work IQ through the Foundry Agent Service.

Built with [Microsoft Agent Framework](https://learn.microsoft.com/agent-framework/overview/agent-framework-overview) and the [Azure AI AgentServer SDK](https://pypi.org/project/azure-ai-agentserver-agentframework/).

## How It Works

The agent uses a local Python tool (`send_to_workiq_agent`) that communicates with Work IQ via the A2A v0.3 protocol. When a user sends a message:

1. The Agent Framework routes the message to the LLM.
2. The LLM decides to call the `send_to_workiq_agent` tool.
3. The tool sends an A2A message to the Work IQ endpoint, including conversation context for multi-turn support.
4. The Work IQ response (text + citations) is returned to the user.

## Prerequisites

1. **Microsoft Foundry Project** — with a chat model deployed (e.g., `gpt-4.1-mini`).
2. **Azure CLI** — installed and authenticated (`az login`).
3. **Python 3.10+** — verify with `python --version`.
4. **Work IQ access** — a valid bearer token for the Work IQ A2A endpoint.

## Environment Variables

| Variable | Description | Required |
|---|---|---|
| `PROJECT_ENDPOINT` | Your Microsoft Foundry project endpoint URL | Yes |
| `MODEL_DEPLOYMENT_NAME` | The deployment name for your chat model (default: `gpt-4.1-mini`) | No |
| `WORKIQ_ENDPOINT` | Work IQ A2A endpoint URL (default: `https://graph.microsoft.com/rp/workiq/`) | Yes |
| `WORKIQ_AUTH_TOKEN` | Bearer token for authenticating to Work IQ | Yes |

Create a `.env` file in this directory:

```env
PROJECT_ENDPOINT=https://<your-resource>.services.ai.azure.com/api/projects/<your-project>
MODEL_DEPLOYMENT_NAME=gpt-4.1-mini
WORKIQ_ENDPOINT=https://graph.microsoft.com/rp/workiq/
WORKIQ_AUTH_TOKEN=<your-jwt-token>
```

## Running Locally

### Set up a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Install dependencies

```powershell
pip install -r requirements.txt
```

### Run the agent

#### Option 1: Press F5 (Recommended)

Press **F5** in VS Code to start debugging. This will start the HTTP server with debugging enabled and open the AI Toolkit Agent Inspector for interactive testing.

#### Option 2: Run in Terminal

```powershell
python main.py
```

The agent starts on `http://localhost:8088/`.

### Test with curl

```powershell
$body = @{
    input = "What meetings do I have today?"
    stream = $false
} | ConvertTo-Json

Invoke-RestMethod -Uri http://localhost:8088/responses -Method Post -Body $body -ContentType "application/json"
```

Or with curl:

```bash
curl -sS -H "Content-Type: application/json" -X POST http://localhost:8088/responses \
  -d '{"input": "What meetings do I have today?", "stream": false}'
```

## Deploying to Microsoft Foundry

1. Open the VS Code Command Palette and run **Microsoft Foundry: Deploy Hosted Agent**.
2. Follow the interactive prompts — the extension builds a container, pushes to ACR, and creates the hosted agent.
3. After deployment, the agent appears under **Hosted Agents (Preview)** in the extension tree.

> **Note:** When deployed, set environment variables in `agent.yaml` rather than `.env`. The `.env` file is for local development only.

### MSI Configuration

Grant the project's managed identity the [Azure AI User](https://aka.ms/foundry-ext-project-role) role:

1. In the Azure Portal, open the Foundry Project → **Access control (IAM)**.
2. Add role assignment → search for **Azure AI User** → assign to the project's managed identity.

## Project Structure

```
foundryHA/
├── .dockerignore     # Docker build exclusions
├── .env              # Local dev environment variables (not committed)
├── .vscode/
│   └── launch.json   # VS Code debug configuration
├── agent.yaml        # Foundry deployment metadata
├── Dockerfile        # Container definition
├── main.py           # Agent entry point (Agent Framework + AgentServer)
├── README.md         # This file
├── requirements.txt  # Python dependencies
└── workiq_tool.py    # A2A client wrapped as an agent tool
```

## Additional Resources

- [Microsoft Agent Framework](https://learn.microsoft.com/agent-framework/overview/agent-framework-overview)
- [Foundry Hosted Agents](https://learn.microsoft.com/azure/ai-foundry/agents/concepts/hosted-agents)
- [A2A Protocol](https://github.com/google/A2A)
