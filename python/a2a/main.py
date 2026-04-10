# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Work IQ A2A Sample — Interactive A2A session via Graph RP.

Usage:
    python main.py --graph --token <JWT>
    python main.py --graph --appid <client-id> [--account user@contoso.com]
    python main.py --graph --appid <client-id> --stream

A Python port of the dotnet/a2a sample from work-iq-samples.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass, field
from typing import Any

from colorama import Fore, Style, init as colorama_init

from a2a.types import (
    Message,
    Task,
    TaskStatusUpdateEvent,
    TextPart,
)

from a2a_client import WorkIQClient
from auth import AuthManager, decode_token
from helpers import (
    Spinner,
    build_message,
    extract_text,
    ink,
    join_text_parts,
    log_header,
    print_citations,
    print_delta,
)


# ── Gateway definitions ──────────────────────────────────────────────

@dataclass
class GatewayConfig:
    name: str
    endpoint: str
    scopes: list[str]
    authority: str
    extra_headers: list[str] = field(default_factory=list)


class Gateways:
    GRAPH = GatewayConfig(
        name="Graph RP",
        endpoint="https://graph.microsoft.com/rp/workiq/",
        scopes=["https://graph.microsoft.com/.default"],
        authority="https://login.microsoftonline.com/common",
    )
    WORKIQ = GatewayConfig(
        name="WorkIQ Gateway",
        endpoint="",  # TODO: set when available
        scopes=[],
        authority="https://login.microsoftonline.com/common",
    )


# ── Config ───────────────────────────────────────────────────────────

@dataclass
class Config:
    token: str
    app_id: str
    gateway: GatewayConfig
    account: str | None
    show_token: bool
    verbosity: int
    stream: bool


# ── Arg parsing ──────────────────────────────────────────────────────

USAGE = """\
Work IQ A2A Sample — Interactive A2A agent session (Python)

Usage: python main.py <gateway> --token <JWT> [options]
       python main.py <gateway> --appid <client-id> [options]

Gateway (exactly one required):
  --graph           Use Microsoft Graph RP gateway
  --workiq          Use WorkIQ Gateway (coming soon)

Auth:
  --token, -t       Bearer JWT token (omit for interactive auth)
  --appid, -a       Azure AD app client ID (required for interactive auth)
  --account         Account hint (e.g. user@contoso.com)

Options:
  --endpoint, -e    Override default gateway endpoint
  --header, -H      Custom HTTP header in 'Key: Value' format (repeatable)
  --show-token      Print the raw JWT token (for reuse with --token)
  --stream          Use streaming mode (SSE via message/stream)
  -v, --verbosity   0 = response only, 1 = default, 2 = full wire (default: 1)

Examples:
  python main.py --graph --appid <your-app-id>
  python main.py --graph --appid <your-app-id> --account user@contoso.com
  python main.py --graph --appid <your-app-id> --stream
  python main.py --graph --token eyJ0eXAi...
"""


def parse_args(args: list[str]) -> Config | None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--graph", action="store_true")
    parser.add_argument("--workiq", action="store_true")
    parser.add_argument("--token", "-t", default=None)
    parser.add_argument("--appid", "-a", default=None)
    parser.add_argument("--account", default=None)
    parser.add_argument("--endpoint", "-e", default=None)
    parser.add_argument("--header", "-H", action="append", default=[])
    parser.add_argument("--show-token", action="store_true")
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("-v", "--verbosity", type=int, default=1)
    parser.add_argument("--help", action="store_true")

    parsed = parser.parse_args(args)

    if parsed.help:
        print(USAGE)
        return None

    # Validate gateway selection
    if not parsed.token and not parsed.appid:
        print(USAGE)
        return None

    if not parsed.graph and not parsed.workiq:
        print(USAGE)
        return None

    if parsed.graph and parsed.workiq:
        ink("ERROR: specify --graph or --workiq, not both\n", Fore.RED)
        return None

    if parsed.workiq:
        ink("ERROR: --workiq gateway is not yet implemented\n", Fore.YELLOW)
        return None

    # Select gateway
    gw = Gateways.GRAPH if parsed.graph else Gateways.WORKIQ

    # Override endpoint if specified
    if parsed.endpoint:
        gw = GatewayConfig(
            name=gw.name,
            endpoint=parsed.endpoint,
            scopes=gw.scopes,
            authority=gw.authority,
            extra_headers=gw.extra_headers + parsed.header,
        )
    elif parsed.header:
        gw = GatewayConfig(
            name=gw.name,
            endpoint=gw.endpoint,
            scopes=gw.scopes,
            authority=gw.authority,
            extra_headers=gw.extra_headers + parsed.header,
        )

    return Config(
        token=parsed.token or "",
        app_id=parsed.appid or "",
        gateway=gw,
        account=parsed.account,
        show_token=parsed.show_token,
        verbosity=parsed.verbosity,
        stream=parsed.stream,
    )


# ── Main ─────────────────────────────────────────────────────────────

async def main() -> None:
    colorama_init()

    config = parse_args(sys.argv[1:])
    if config is None:
        return

    # ── Resolve token ────────────────────────────────────────────────
    auth_mgr: AuthManager | None = None

    if config.token:
        token = config.token
    else:
        if not config.app_id:
            ink("ERROR: --appid is required for interactive auth (or provide --token)\n", Fore.RED)
            return
        auth_mgr = AuthManager(
            client_id=config.app_id,
            scopes=config.gateway.scopes,
            authority=config.gateway.authority,
            account_hint=config.account,
        )
        token = auth_mgr.get_token(config.verbosity)

    # ── Display token info ───────────────────────────────────────────
    if config.verbosity >= 1:
        log_header("TOKEN")
        decode_token(token)
        if config.show_token:
            print(f"\n  {token}\n")

    # ── Set up A2A client ────────────────────────────────────────────
    client = WorkIQClient(
        endpoint=config.gateway.endpoint,
        token=token,
        extra_headers=config.gateway.extra_headers,
        stream=config.stream,
    )
    context_id: str | None = None

    if config.verbosity >= 1:
        mode = "Streaming" if config.stream else "Sync"
        log_header(f"READY — {config.gateway.name} — {mode} — {config.gateway.endpoint}")
        if auth_mgr:
            acct = auth_mgr.cached_account()
            if acct:
                ink(f"  Signed in as {acct}\n", Fore.CYAN)
        print("Type a message. 'quit' to exit.\n")

    # ── Interactive REPL ─────────────────────────────────────────────
    try:
        while True:
            if config.verbosity >= 1:
                ink("You > ", Fore.CYAN)

            try:
                user_input = input()
            except EOFError:
                break

            if not user_input.strip():
                continue
            if user_input.strip().lower() in ("quit", "exit"):
                break

            # Silent token refresh
            if auth_mgr:
                try:
                    fresh = auth_mgr.ensure_fresh(config.verbosity)
                    if fresh != token:
                        token = fresh
                        client.update_token(token)
                except Exception:
                    pass  # use cached token

            if config.verbosity >= 1:
                ink("Agent > ", Fore.GREEN)

            spinner = Spinner()
            spinner.start()

            try:
                msg = build_message(user_input, context_id)
                start_time = time.monotonic()
                response_metadata: dict[str, Any] | None = None

                if config.stream:
                    previous_text = ""
                    async for event in client.send_message(msg):
                        # event is either a Message or a (Task, UpdateEvent) tuple
                        text, ctx, meta = extract_text(event)
                        if ctx:
                            context_id = ctx
                        if meta:
                            response_metadata = meta

                        # Show event details at verbosity >= 1
                        if config.verbosity >= 1 and isinstance(event, tuple):
                            task_obj, update_event = event
                            if isinstance(task_obj, Task) and task_obj.status:
                                state = task_obj.status.state
                                parts_desc = []
                                if task_obj.status.message and task_obj.status.message.parts:
                                    for p in task_obj.status.message.parts:
                                        inner = p.root if hasattr(p, "root") else p
                                        if isinstance(inner, TextPart):
                                            parts_desc.append(f"TextPart({len(inner.text or '')}c)")
                                        else:
                                            parts_desc.append(type(inner).__name__)
                                ink(f"  [{state}] {' + '.join(parts_desc)}\n", Fore.WHITE + Style.DIM)

                        spinner.stop()
                        # Print text delta
                        previous_text, _ = print_delta(text, previous_text)

                        # Check for completion
                        if isinstance(event, tuple):
                            task_obj, _ = event
                            if isinstance(task_obj, Task) and task_obj.status:
                                if task_obj.status.state in ("completed", "failed", "canceled"):
                                    break

                    elapsed = (time.monotonic() - start_time) * 1000
                    spinner.stop()
                    print()  # newline after streaming
                else:
                    # Sync mode: collect the first complete response
                    async for event in client.send_message(msg):
                        text, ctx, meta = extract_text(event)
                        if ctx:
                            context_id = ctx
                        response_metadata = meta
                        break  # Only need the first complete response

                    elapsed = (time.monotonic() - start_time) * 1000
                    spinner.stop()
                    print(text)

                if config.verbosity >= 1:
                    ink(f"  ({elapsed:.0f} ms)\n", Fore.WHITE + Style.DIM)

                # Print citations
                if response_metadata:
                    print_citations(response_metadata, config.verbosity)

            except Exception as ex:
                spinner.stop()
                ink(f"\n  ERROR: {type(ex).__name__}: {ex}\n", Fore.RED)

            print()  # blank line between turns

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
