# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for the Work IQ A2A Python sample.

Matches the testing patterns from the dotnet and Rust samples.
"""

from __future__ import annotations

import io
import sys
from unittest.mock import patch

import pytest

# Add parent directory to path so we can import the sample modules
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from helpers import (
    Spinner,
    build_message,
    extract_text,
    join_text_parts,
    print_citations,
    print_delta,
)
from auth import decode_token


# ── Lazy imports for a2a types ───────────────────────────────────────
# These are imported here so tests can run even if a2a-sdk types change

from a2a.types import (
    Message,
    Part,
    Role,
    Task,
    TaskState,
    TaskStatus,
    TextPart,
)


# ── build_message ────────────────────────────────────────────────────

class TestBuildMessage:
    def test_structure(self):
        msg = build_message("hello")
        assert msg.kind == "message"
        assert msg.role == Role.user
        assert len(msg.parts) == 1
        # Parts are wrapped in Part(root=TextPart(...))
        inner = msg.parts[0].root if hasattr(msg.parts[0], "root") else msg.parts[0]
        assert isinstance(inner, TextPart)
        assert inner.text == "hello"
        assert msg.context_id is None
        assert msg.message_id is not None and len(msg.message_id) > 0

    def test_with_context_id(self):
        msg = build_message("reply", context_id="ctx-42")
        assert msg.context_id == "ctx-42"

    def test_has_location_metadata(self):
        msg = build_message("test")
        assert msg.metadata is not None
        assert "Location" in msg.metadata
        loc = msg.metadata["Location"]
        assert "timeZoneOffset" in loc
        assert "timeZone" in loc

    def test_empty_text(self):
        msg = build_message("")
        assert len(msg.parts) == 1
        inner = msg.parts[0].root if hasattr(msg.parts[0], "root") else msg.parts[0]
        assert isinstance(inner, TextPart)
        assert inner.text == ""
        assert msg.kind == "message"

    def test_special_characters(self):
        text = 'He said "hello"\nnew line\ttab \U0001f680 café'
        msg = build_message(text)
        inner = msg.parts[0].root if hasattr(msg.parts[0], "root") else msg.parts[0]
        assert isinstance(inner, TextPart)
        assert inner.text == text

    def test_unique_message_ids(self):
        msg1 = build_message("a")
        msg2 = build_message("b")
        assert msg1.message_id != msg2.message_id


# ── join_text_parts ──────────────────────────────────────────────────

class TestJoinTextParts:
    def test_basic(self):
        parts = [
            TextPart(kind="text", text="hello"),
            TextPart(kind="text", text="world"),
        ]
        assert join_text_parts(parts) == "hello\nworld"

    def test_single(self):
        parts = [TextPart(kind="text", text="only")]
        assert join_text_parts(parts) == "only"

    def test_empty(self):
        assert join_text_parts([]) == ""
        assert join_text_parts(None) == ""

    def test_with_newlines_in_text(self):
        parts = [
            TextPart(kind="text", text="line1\nline2"),
            TextPart(kind="text", text="line3\nline4"),
        ]
        assert join_text_parts(parts) == "line1\nline2\nline3\nline4"


# ── extract_text ─────────────────────────────────────────────────────

class TestExtractText:
    def test_from_message(self):
        msg = Message(
            kind="message",
            role=Role.agent,
            message_id="m1",
            context_id="ctx-1",
            parts=[TextPart(kind="text", text="response")],
            metadata={"key": "val"},
        )
        text, ctx, meta = extract_text(msg)
        assert text == "response"
        assert ctx == "ctx-1"
        assert meta is not None
        assert meta["key"] == "val"

    def test_from_task_completed(self):
        task = Task(
            kind="task",
            id="t1",
            context_id="ctx-2",
            status=TaskStatus(
                state=TaskState.completed,
                message=Message(
                    kind="message",
                    role=Role.agent,
                    message_id="m2",
                    parts=[TextPart(kind="text", text="done")],
                    metadata={"cite": True},
                ),
            ),
        )
        text, ctx, meta = extract_text(task)
        assert text == "done"
        assert ctx == "ctx-2"
        assert meta is not None
        assert meta["cite"] is True

    def test_from_task_without_message(self):
        task = Task(
            kind="task",
            id="t2",
            context_id="ctx-3",
            status=TaskStatus(
                state=TaskState.working,
            ),
        )
        text, ctx, _ = extract_text(task)
        assert "t2" in text
        assert "working" in text
        assert ctx == "ctx-3"

    def test_from_task_empty_parts(self):
        task = Task(
            kind="task",
            id="t-empty",
            context_id="ctx-e",
            status=TaskStatus(
                state=TaskState.completed,
                message=Message(
                    kind="message",
                    role=Role.agent,
                    message_id="m-empty",
                    parts=[],
                ),
            ),
        )
        text, ctx, _ = extract_text(task)
        assert text == ""
        assert ctx == "ctx-e"

    def test_from_tuple(self):
        """ClientFactory returns (Task, UpdateEvent) tuples."""
        task = Task(
            kind="task",
            id="t3",
            context_id="ctx-4",
            status=TaskStatus(
                state=TaskState.completed,
                message=Message(
                    kind="message",
                    role=Role.agent,
                    message_id="m3",
                    parts=[TextPart(kind="text", text="tuple response")],
                ),
            ),
        )
        text, ctx, _ = extract_text((task, None))
        assert text == "tuple response"
        assert ctx == "ctx-4"

    def test_from_message_tuple(self):
        """ClientFactory may also return Message directly."""
        msg = Message(
            kind="message",
            role=Role.agent,
            message_id="m4",
            context_id="ctx-5",
            parts=[TextPart(kind="text", text="msg tuple")],
        )
        text, ctx, _ = extract_text((msg, None))
        assert text == "msg tuple"
        assert ctx == "ctx-5"

    def test_unknown_type(self):
        text, ctx, meta = extract_text("something unexpected")
        assert text == "(no response)"
        assert ctx is None


# ── print_delta ──────────────────────────────────────────────────────

class TestPrintDelta:
    def test_incremental(self, capsys):
        prev, _ = print_delta("Hello", "")
        assert prev == "Hello"
        captured = capsys.readouterr()
        assert captured.out == "Hello"

        prev, _ = print_delta("Hello world", prev)
        assert prev == "Hello world"
        captured = capsys.readouterr()
        assert captured.out == " world"

    def test_full_replace(self, capsys):
        prev, _ = print_delta("completely new", "old text")
        assert prev == "completely new"
        captured = capsys.readouterr()
        assert captured.out == "completely new"

    def test_empty(self, capsys):
        prev, _ = print_delta("", "")
        assert prev == ""


# ── print_citations ──────────────────────────────────────────────────

class TestPrintCitations:
    def test_no_metadata(self, capsys):
        print_citations(None, 1)
        assert capsys.readouterr().out == ""

    def test_no_attributions(self, capsys):
        print_citations({"other": "data"}, 1)
        assert capsys.readouterr().out == ""

    def test_empty_attributions(self, capsys):
        print_citations({"attributions": []}, 1)
        assert capsys.readouterr().out == ""

    def test_citation_counts(self, capsys):
        metadata = {
            "attributions": [
                {
                    "attributionType": "Citation",
                    "attributionSource": "Model",
                    "providerDisplayName": "Meeting Notes",
                    "seeMoreWebUrl": "https://example.com/1",
                },
                {
                    "attributionType": "Annotation",
                    "attributionSource": "Model",
                    "providerDisplayName": "John Doe",
                    "seeMoreWebUrl": "",
                },
            ]
        }
        print_citations(metadata, 1)
        captured = capsys.readouterr().out
        assert "Citations: 1" in captured
        assert "Annotations: 1" in captured

    def test_verbosity_2_details(self, capsys):
        metadata = {
            "attributions": [
                {
                    "attributionType": "Citation",
                    "attributionSource": "Model",
                    "providerDisplayName": "Q3 Planning",
                    "seeMoreWebUrl": "https://teams.microsoft.com/meeting",
                },
            ]
        }
        print_citations(metadata, 2)
        captured = capsys.readouterr().out
        assert "Q3 Planning" in captured
        assert "teams.microsoft.com" in captured

    def test_verbosity_0_silent(self, capsys):
        metadata = {
            "attributions": [
                {
                    "attributionType": "Citation",
                    "attributionSource": "Model",
                    "providerDisplayName": "Test",
                    "seeMoreWebUrl": "",
                },
            ]
        }
        print_citations(metadata, 0)
        assert capsys.readouterr().out == ""

    def test_truncates_long_urls(self, capsys):
        metadata = {
            "attributions": [
                {
                    "attributionType": "Citation",
                    "attributionSource": "Model",
                    "providerDisplayName": "Long URL",
                    "seeMoreWebUrl": "https://example.com/" + "x" * 200,
                },
            ]
        }
        print_citations(metadata, 2)
        captured = capsys.readouterr().out
        assert "..." in captured


# ── decode_token ─────────────────────────────────────────────────────

class TestDecodeToken:
    def _make_jwt(self, claims: dict) -> str:
        """Create a minimal unsigned JWT for testing."""
        import base64, json
        header = base64.urlsafe_b64encode(json.dumps({"typ": "JWT", "alg": "none"}).encode()).rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
        return f"{header}.{payload}."

    def test_valid_token(self, capsys):
        token = self._make_jwt({
            "aud": "https://graph.microsoft.com",
            "upn": "user@contoso.com",
            "name": "Test User",
            "scp": "Sites.Read.All Mail.Read",
        })
        decode_token(token)
        captured = capsys.readouterr().out
        assert "graph.microsoft.com" in captured
        assert "user@contoso.com" in captured
        assert "Test User" in captured

    def test_invalid_not_jwt(self, capsys):
        decode_token("not-a-jwt")
        captured = capsys.readouterr().out
        assert "not a valid JWT" in captured

    def test_empty_claims(self, capsys):
        token = self._make_jwt({})
        decode_token(token)
        # Should not crash, just no output for missing claims

    def test_with_expiry(self, capsys):
        import time
        token = self._make_jwt({
            "aud": "https://graph.microsoft.com",
            "exp": int(time.time()) + 3600,  # 1 hour from now
        })
        decode_token(token)
        captured = capsys.readouterr().out
        assert "expires" in captured
        assert "60m" in captured or "59m" in captured

    def test_expired_token(self, capsys):
        token = self._make_jwt({
            "aud": "https://graph.microsoft.com",
            "exp": 1000000000,  # long ago
        })
        decode_token(token)
        captured = capsys.readouterr().out
        assert "EXPIRED" in captured


# ── parse_args ───────────────────────────────────────────────────────

class TestParseArgs:
    def test_basic_jwt(self):
        from main import parse_args
        config = parse_args(["--graph", "--token", "eyJtoken"])
        assert config is not None
        assert config.token == "eyJtoken"
        assert config.gateway.name == "Graph RP"
        assert config.stream is False

    def test_streaming(self):
        from main import parse_args
        config = parse_args(["--graph", "--token", "tok", "--stream"])
        assert config is not None
        assert config.stream is True

    def test_appid(self):
        from main import parse_args
        config = parse_args(["--graph", "--appid", "my-app-id"])
        assert config is not None
        assert config.app_id == "my-app-id"

    def test_verbosity(self):
        from main import parse_args
        config = parse_args(["--graph", "--token", "tok", "-v", "2"])
        assert config is not None
        assert config.verbosity == 2

    def test_custom_endpoint(self):
        from main import parse_args
        config = parse_args(["--graph", "--token", "tok", "--endpoint", "https://custom.endpoint/"])
        assert config is not None
        assert config.gateway.endpoint == "https://custom.endpoint/"

    def test_custom_headers(self):
        from main import parse_args
        config = parse_args(["--graph", "--token", "tok", "-H", "X-Custom: value"])
        assert config is not None
        assert "X-Custom: value" in config.gateway.extra_headers

    def test_no_args_returns_none(self, capsys):
        from main import parse_args
        config = parse_args([])
        assert config is None

    def test_both_gateways_returns_none(self, capsys):
        from main import parse_args
        config = parse_args(["--graph", "--workiq", "--token", "tok"])
        assert config is None

    def test_workiq_not_implemented(self, capsys):
        from main import parse_args
        config = parse_args(["--workiq", "--token", "tok"])
        assert config is None

    def test_show_token(self):
        from main import parse_args
        config = parse_args(["--graph", "--token", "tok", "--show-token"])
        assert config is not None
        assert config.show_token is True

    def test_account_hint(self):
        from main import parse_args
        config = parse_args(["--graph", "--appid", "id", "--account", "user@test.com"])
        assert config is not None
        assert config.account == "user@test.com"


# ── Spinner ──────────────────────────────────────────────────────────

class TestSpinner:
    def test_start_stop(self):
        spinner = Spinner()
        spinner.start()
        assert spinner._running is True
        spinner.stop()
        assert spinner._running is False

    def test_double_stop(self):
        spinner = Spinner()
        spinner.start()
        spinner.stop()
        spinner.stop()  # Should not crash

    def test_no_start_stop(self):
        spinner = Spinner()
        spinner.stop()  # Should not crash
