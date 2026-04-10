# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Shared helpers for the Work IQ A2A Python sample.

Includes message building, response extraction, citation printing,
spinner animation, and colored output.
"""

from __future__ import annotations

import sys
import time
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from colorama import Fore, Style

from a2a.types import (
    Message,
    MessageSendConfiguration,
    Part,
    Role,
    Task,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)


# ── Message building ─────────────────────────────────────────────────

def build_message(text: str, context_id: str | None = None) -> Message:
    """Build an A2A v0.3 user message with Location metadata (timezone info)."""
    now = datetime.now(timezone.utc).astimezone()
    offset_minutes = int(now.utcoffset().total_seconds() / 60) if now.utcoffset() else 0

    try:
        tz_name = str(now.tzinfo)
    except Exception:
        tz_name = "Unknown"

    # Try to get IANA timezone name on platforms that support it
    try:
        import zoneinfo
        # The astimezone() tzinfo may have a .key attribute
        tz_key = getattr(now.tzinfo, "key", None)
        if tz_key:
            tz_name = tz_key
        else:
            # Fallback: use the tzname
            tz_name = now.tzname() or "Unknown"
    except ImportError:
        tz_name = now.tzname() or "Unknown"

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


# ── Response extraction ──────────────────────────────────────────────

def extract_text(response: Any) -> tuple[str, str | None, dict[str, Any] | None]:
    """Extract (text, contextId, metadata) from a Task, Message, or (Task, event) tuple.

    Handles:
    - Message directly
    - Task with status.message
    - (Task, TaskStatusUpdateEvent) tuple from ClientFactory
    - (Task, None) tuple
    """
    # Handle (Task, UpdateEvent) tuples from ClientFactory.create() client
    if isinstance(response, tuple) and len(response) == 2:
        task, event = response
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
    text = join_text_parts(msg.parts)
    return (text, msg.context_id, msg.metadata)


def _extract_from_task(task: Task) -> tuple[str, str | None, dict[str, Any] | None]:
    if task.status and task.status.message:
        cm = task.status.message
        text = join_text_parts(cm.parts)
        meta = cm.metadata or (task.metadata if hasattr(task, "metadata") else None)
        return (text, task.context_id, meta)
    state = task.status.state if task.status else "unknown"
    return (f"[Task {task.id} — {state}]", task.context_id, None)


def join_text_parts(parts: list[Part] | None) -> str:
    """Join all TextPart texts with newlines.

    Parts in the a2a-sdk are wrapped in a Part discriminated union.
    Access .root to get the actual TextPart/DataPart/FilePart.
    """
    if not parts:
        return ""
    texts = []
    for p in parts:
        # Unwrap Part discriminated union if needed
        inner = p.root if hasattr(p, "root") else p
        if isinstance(inner, TextPart) and inner.text is not None:
            texts.append(inner.text)
    return "\n".join(texts)


# ── Citations ────────────────────────────────────────────────────────

def print_citations(metadata: dict[str, Any] | None, verbosity: int) -> None:
    """Parse and display citations from metadata['attributions']."""
    if not metadata or "attributions" not in metadata:
        return

    attrs = metadata["attributions"]
    if not isinstance(attrs, list) or len(attrs) == 0:
        return

    citations: list[dict[str, str]] = []
    for attr in attrs:
        if not isinstance(attr, dict):
            continue
        citations.append({
            "type": attr.get("attributionType", ""),
            "source": attr.get("attributionSource", ""),
            "provider": attr.get("providerDisplayName", ""),
            "url": attr.get("seeMoreWebUrl", ""),
        })

    if not citations:
        return

    citation_count = sum(1 for c in citations if "citation" in c["type"].lower())
    annotation_count = sum(1 for c in citations if "annotation" in c["type"].lower())

    if verbosity >= 1:
        ink(f"  Citations: {citation_count}  Annotations: {annotation_count}\n", Fore.YELLOW)

    if verbosity >= 2:
        for c in citations:
            is_citation = "citation" in c["type"].lower()
            label = "\U0001f4c4" if is_citation else "\U0001f517"  # 📄 or 🔗
            name = c["provider"] if c["provider"] else "(unnamed)"
            color = Fore.YELLOW if is_citation else (Fore.WHITE + Style.DIM)
            ink(f"    {label} [{c['type']}/{c['source']}] {name}\n", color)
            if c["url"]:
                truncated = c["url"][:120] + "..." if len(c["url"]) > 120 else c["url"]
                ink(f"       {truncated}\n", Fore.WHITE + Style.DIM)


# ── Delta printing ───────────────────────────────────────────────────

def print_delta(combined: str, previous_text: str) -> tuple[str, None]:
    """Print only new text since last update. Returns updated previous_text."""
    if combined.startswith(previous_text):
        sys.stdout.write(combined[len(previous_text):])
    else:
        sys.stdout.write(combined)
    sys.stdout.flush()
    return combined, None  # Return as tuple for easy unpacking


# ── Spinner ──────────────────────────────────────────────────────────

class Spinner:
    """Animated waiting indicator matching the dotnet/Rust spinner frames."""

    FRAMES = ["·  ", "·· ", "···", " ··", "  ·", "   "]

    def __init__(self) -> None:
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._thread:
            self._thread.join(timeout=1)
            self._thread = None
        # Clear spinner area
        sys.stdout.write("   \b\b\b")
        sys.stdout.flush()

    def _spin(self) -> None:
        i = 0
        while self._running:
            frame = self.FRAMES[i % len(self.FRAMES)]
            sys.stdout.write(frame)
            sys.stdout.flush()
            sys.stdout.write("\b" * len(frame))
            time.sleep(0.15)
            i += 1


# ── Console utilities ────────────────────────────────────────────────

def ink(text: str, color: str) -> None:
    """Print colored text without trailing newline (text should include \\n if needed)."""
    sys.stdout.write(f"{color}{text}{Style.RESET_ALL}")
    sys.stdout.flush()


def log_header(label: str) -> None:
    """Print a section header."""
    ink(f"\n── {label} ──\n", Fore.WHITE + Style.DIM)
