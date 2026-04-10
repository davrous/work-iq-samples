# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Work IQ A2A tool for the Foundry Hosted Agent.

Wraps the A2A v0.3 client from the original sample as a local tool function
that can be invoked by the Microsoft Agent Framework agent.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

import httpx
from a2a.client import (
    BaseClient,
    ClientConfig,
    ClientFactory,
    minimal_agent_card,
)
from a2a.types import (
    AgentCapabilities,
    Message,
    Part,
    Role,
    Task,
    TextPart,
)

logger = logging.getLogger(__name__)

# Module-level context_id for multi-turn A2A conversations
_context_id: str | None = None


# ── A2A message helpers (adapted from a2a/helpers.py) ────────────────

def _build_message(text: str, context_id: str | None = None) -> Message:
    """Build an A2A v0.3 user message with timezone metadata."""
    now = datetime.now(timezone.utc).astimezone()
    offset_minutes = int(now.utcoffset().total_seconds() / 60) if now.utcoffset() else 0

    try:
        tz_name = now.tzname() or "Unknown"
    except Exception:
        tz_name = "Unknown"

    return Message(
        kind="message",
        role=Role.user,
        message_id=str(uuid.uuid4()),
        context_id=context_id,
        parts=[TextPart(kind="text", text=text)],
        metadata={
            "Location": {
                "timeZoneOffset": offset_minutes,
                "timeZone": tz_name,
            },
        },
    )


def _join_text_parts(parts: list[Part] | None) -> str:
    """Join all TextPart texts from an A2A response."""
    if not parts:
        return ""
    texts = []
    for p in parts:
        inner = p.root if hasattr(p, "root") else p
        if isinstance(inner, TextPart) and inner.text is not None:
            texts.append(inner.text)
    return "\n".join(texts)


def _extract_text(response: Any) -> tuple[str, str | None, dict[str, Any] | None]:
    """Extract (text, contextId, metadata) from an A2A response object."""
    if isinstance(response, tuple) and len(response) == 2:
        task, _event = response
        if isinstance(task, Task):
            return _extract_from_task(task)
        if isinstance(task, Message):
            return _extract_from_message(task)

    if isinstance(response, Message):
        return _extract_from_message(response)

    if isinstance(response, Task):
        return _extract_from_task(response)

    return ("(no response)", None, None)


def _extract_from_message(msg: Message) -> tuple[str, str | None, dict[str, Any] | None]:
    text = _join_text_parts(msg.parts)
    return (text, msg.context_id, msg.metadata)


def _extract_from_task(task: Task) -> tuple[str, str | None, dict[str, Any] | None]:
    if task.status and task.status.message:
        cm = task.status.message
        text = _join_text_parts(cm.parts)
        meta = cm.metadata or (task.metadata if hasattr(task, "metadata") else None)
        return (text, task.context_id, meta)
    state = task.status.state if task.status else "unknown"
    return (f"[Task {task.id} — {state}]", task.context_id, None)


def _format_citations(metadata: dict[str, Any] | None) -> str:
    """Format citations from metadata['attributions'] as text."""
    if not metadata or "attributions" not in metadata:
        return ""

    attrs = metadata["attributions"]
    if not isinstance(attrs, list) or len(attrs) == 0:
        return ""

    lines: list[str] = []
    for attr in attrs:
        if not isinstance(attr, dict):
            continue
        attr_type = attr.get("attributionType", "")
        provider = attr.get("providerDisplayName", "")
        url = attr.get("seeMoreWebUrl", "")
        source = attr.get("attributionSource", "")
        label = provider if provider else source
        if url:
            lines.append(f"- [{label}]({url})")
        elif label:
            lines.append(f"- {label} ({attr_type})")

    if not lines:
        return ""

    return "\n\n**Sources:**\n" + "\n".join(lines)


# ── The tool function exposed to the Agent Framework ─────────────────

async def send_to_workiq_agent(
    message: Annotated[str, "The user's message or question to send to the Work IQ agent"],
) -> str:
    """
    Send a message to the Work IQ agent via the A2A protocol and return its response.
    Use this tool whenever the user asks a question or makes a request that should be
    handled by Work IQ. This supports multi-turn conversations — context is preserved
    across calls.
    """
    global _context_id

    endpoint = os.getenv("WORKIQ_ENDPOINT", "")
    token = os.getenv("WORKIQ_AUTH_TOKEN", "")

    if not endpoint:
        return "Error: WORKIQ_ENDPOINT environment variable is not set."
    if not token:
        return "Error: WORKIQ_AUTH_TOKEN environment variable is not set."

    # Build A2A message
    a2a_message = _build_message(message, _context_id)

    # Set up httpx client with auth
    headers = {
        "Authorization": f"Bearer {token}",
    }

    try:
        async with httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(300.0),
        ) as http_client:
            # Create A2A SDK client
            card = minimal_agent_card(endpoint)
            card.capabilities = AgentCapabilities(streaming=False)

            config = ClientConfig(
                streaming=False,
                httpx_client=http_client,
            )
            factory = ClientFactory(config)
            client: BaseClient = factory.create(card)

            # Send message and collect the first complete response
            response_text = "(no response from Work IQ)"
            response_metadata = None

            async for event in client.send_message(a2a_message):
                text, ctx, meta = _extract_text(event)
                if ctx:
                    _context_id = ctx
                if meta:
                    response_metadata = meta
                response_text = text
                break  # First complete response in sync mode

            # Append citations if present
            citations = _format_citations(response_metadata)
            if citations:
                response_text += citations

            logger.info("Work IQ response received (context_id=%s)", _context_id)
            return response_text

    except httpx.TimeoutException:
        logger.error("Timeout calling Work IQ endpoint: %s", endpoint)
        return "Error: The request to Work IQ timed out. Please try again."
    except Exception as e:
        logger.error("Error calling Work IQ: %s: %s", type(e).__name__, e)
        return f"Error communicating with Work IQ: {type(e).__name__}: {e}"
