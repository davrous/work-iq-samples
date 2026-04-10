# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Thin wrapper around the a2a-sdk Python client configured for Work IQ (A2A v0.3).

Uses ClientFactory with a minimal_agent_card to bypass agent card discovery
and a custom httpx.AsyncClient for auth headers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from a2a.client import (
    BaseClient,
    ClientConfig,
    ClientEvent,
    ClientFactory,
    minimal_agent_card,
)
from a2a.types import (
    AgentCapabilities,
    Message,
    MessageSendConfiguration,
)


class WorkIQClient:
    """A2A client configured for the Work IQ endpoint."""

    def __init__(
        self,
        endpoint: str,
        token: str,
        extra_headers: list[str] | None = None,
        stream: bool = False,
    ) -> None:
        self._endpoint = endpoint
        self._stream = stream

        # Build httpx client with auth + extra headers
        headers: dict[str, str] = {
            "Authorization": f"Bearer {token}",
        }
        for h in extra_headers or []:
            parts = h.split(":", 1)
            if len(parts) == 2:
                headers[parts[0].strip()] = parts[1].strip()

        self._httpx = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(300.0),
        )

        # Create a minimal agent card — bypasses /.well-known/agent.json discovery
        card = minimal_agent_card(endpoint)
        # Enable streaming capability on the card
        card.capabilities = AgentCapabilities(streaming=True)

        # Create SDK client via factory
        config = ClientConfig(
            streaming=stream,
            httpx_client=self._httpx,
        )
        factory = ClientFactory(config)
        self._client: BaseClient = factory.create(card)

    def update_token(self, token: str) -> None:
        """Update the bearer token for subsequent requests."""
        self._httpx.headers["Authorization"] = f"Bearer {token}"

    async def send_message(
        self,
        message: Message,
        *,
        configuration: MessageSendConfiguration | None = None,
    ) -> AsyncIterator[ClientEvent | Message]:
        """Send a message and yield responses (sync or streaming based on config)."""
        async for event in self._client.send_message(
            message, configuration=configuration
        ):
            yield event

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._httpx.aclose()
