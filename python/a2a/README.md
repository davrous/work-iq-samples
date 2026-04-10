# Work IQ A2A Sample (Python)

A minimal, interactive client for communicating with Work IQ agents using the
[Agent-to-Agent (A2A) protocol](https://a2a-protocol.org/) — implemented in Python.

This is a Python port of the [dotnet/a2a](../../../dotnet/a2a/) sample.

> Prerequisites, authentication, and common issues are covered in the
> [root README](../../../README.md). Read that first.

## What is A2A?

The Agent-to-Agent (A2A) Protocol is an open standard for communication between
AI agents. It defines JSON-RPC methods for sending messages, managing tasks, and
streaming responses via Server-Sent Events.

- [A2A Protocol Specification](https://a2a-protocol.org/latest/specification/)
- [A2A Python SDK](https://github.com/a2aproject/a2a-python) (PyPI: [a2a-sdk](https://pypi.org/project/a2a-sdk/))

## Quick start

```bash
# Install dependencies
pip install -r requirements.txt

# With a pre-obtained JWT token (any platform)
python main.py --graph --token eyJ0eXAiOiJKV1Qi...

# With interactive auth — browser PKCE (any platform)
python main.py --graph --appid <your-app-client-id>

# Streaming mode
python main.py --graph --appid <your-app-client-id> --stream

# With account hint
python main.py --graph --appid <your-app-client-id> --account user@contoso.com
```

> **Note:** This sample uses MSAL's browser-based auth code flow with PKCE as
> the primary interactive method, with device code flow as a fallback. Unlike
> the .NET sample, WAM (Windows Account Manager) is not used.

## Parameters

| Flag | Description |
|---|---|
| `--graph` | Use Microsoft Graph RP gateway (required) |
| `--token`, `-t` | Bearer JWT token (omit for interactive auth) |
| `--appid`, `-a` | Azure AD app client ID (required for interactive auth) |
| `--account` | Account hint for MSAL (e.g. `user@contoso.com`) |
| `--endpoint`, `-e` | Override the default gateway endpoint URL |
| `--header`, `-H` | Custom HTTP header in `Key: Value` format (repeatable) |
| `--show-token` | Print the raw JWT after decoding (for reuse) |
| `--stream` | Use streaming mode (SSE via `message/stream`) |
| `-v`, `--verbosity` | `0` = response only, `1` = default, `2` = full wire diagnostics |

## How it works

```
┌──────────────┐     JSON-RPC POST       ┌──────────────────┐
│  This Sample │ ──────────────────────>  │  Microsoft Graph │
│  (A2A Client)│ <──────────────────────  │  Copilot API     │
└──────────────┘   AgentMessage response  └──────────────────┘
```

1. **Auth**: Acquires a token via browser PKCE, device code, or accepts a
   pre-obtained JWT
2. **A2A Client**: Creates a client from the
   [A2A Python SDK](https://github.com/a2aproject/a2a-python) pointed at the
   Graph RP endpoint
3. **Send**: Sends `message/send` (sync) or `message/stream` (streaming) JSON-RPC
   requests
4. **Receive**: Parses `Message` or `Task` responses, extracts text and citations
5. **Multi-turn**: Maintains `contextId` across turns for conversation continuity

## A2A protocol compliance

| Feature | Status | Notes |
|---|---|---|
| `message/send` (sync) | ✅ Available | Full request/response cycle |
| `message/stream` (SSE) | ✅ Available | Incremental streaming via TaskStatusUpdateEvent |
| Multi-turn (`contextId`) | ✅ Available | Conversation state maintained across turns |
| `TextPart` messages | ✅ Available | User and agent text messages |
| Citations | ✅ Available | Via Microsoft-specific `metadata["attributions"]` |
| Agent card (`/.well-known/agent.json`) | 🔜 Coming soon | Connect to endpoint directly for now |
| Agent discovery / listing | 🔜 Coming soon | Connects to M365 Copilot agent directly for now |

## Authentication methods

| Method | Platforms | When used |
|---|---|---|
| Browser auth code (PKCE) | Windows, macOS, Linux | Primary interactive method — opens browser |
| Device code flow | Windows, macOS, Linux | Fallback when browser fails (headless) |
| Pre-obtained JWT | Windows, macOS, Linux | Pass directly via `--token` |

## Citations

Citations are delivered via a Microsoft-specific extension to the A2A protocol
under `Message.metadata["attributions"]`. This is not part of the
[A2A spec](https://a2a-protocol.org/) and is subject to change.

```json
[
  {
    "attributionType": "Citation",
    "attributionSource": "Model",
    "providerDisplayName": "Q3 Planning Meeting",
    "seeMoreWebUrl": "https://teams.microsoft.com/..."
  }
]
```

| Type | Meaning |
|---|---|
| `Citation` | Source explicitly referenced in the response text (e.g., [1]) |
| `Annotation` | Entity recognized in the response but not numbered |

Use `-v 2` to see full citation details in the output.

## Wire diagnostics

Use `-v 2` to see verbose output including A2A event details:

```
  [working] TextPart(42c)
  [working] TextPart(128c)
  [completed] TextPart(256c)
```

## Project structure

```
python/a2a/
├── main.py           # Entry point, CLI, interactive REPL
├── a2a_client.py     # A2A SDK client wrapper for Work IQ
├── auth.py           # MSAL authentication (browser PKCE + device code)
├── helpers.py        # Message building, extraction, citations, spinner
├── requirements.txt  # Python dependencies
├── README.md         # This file
└── tests/
    └── test_main.py  # Unit tests
```

## Dependencies

| Package | Purpose |
|---|---|
| [a2a-sdk](https://pypi.org/project/a2a-sdk/) (≥ 0.3.20) | A2A protocol client and types |
| [msal](https://pypi.org/project/msal/) (≥ 1.28.0) | MSAL token acquisition (browser PKCE + device code) |
| [httpx](https://pypi.org/project/httpx/) (≥ 0.27.0) | HTTP client (also a dependency of a2a-sdk) |
| [PyJWT](https://pypi.org/project/PyJWT/) (≥ 2.8.0) | JWT decoding for diagnostics |
| [colorama](https://pypi.org/project/colorama/) (≥ 0.4.6) | Cross-platform colored terminal output |

> **Note:** This sample uses A2A SDK v0.3.x. The spec has since moved to v1.0.
> This sample will be updated when the server supports v1.0.

## Resources

- [A2A Protocol Specification](https://a2a-protocol.org/latest/specification/)
- [A2A Python SDK](https://github.com/a2aproject/a2a-python)
- [Work IQ Overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/workiq-overview)
