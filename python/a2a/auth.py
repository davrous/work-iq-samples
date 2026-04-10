# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Authentication module for Work IQ A2A sample.

Supports (in order): silent cached → browser auth code with PKCE → device code flow.
Also accepts a pre-obtained JWT token.
"""

from __future__ import annotations

import base64
import json
import secrets
import socket
import threading
import webbrowser
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

import msal
from colorama import Fore, Style


# ── AuthManager ──────────────────────────────────────────────────────

class AuthManager:
    """Manages the full token lifecycle using MSAL:
    silent → browser auth code (PKCE) → device code.
    """

    def __init__(
        self,
        client_id: str,
        scopes: list[str],
        authority: str,
        account_hint: str | None = None,
    ) -> None:
        self._app = msal.PublicClientApplication(
            client_id,
            authority=authority,
        )
        self._scopes = scopes
        self._account_hint = account_hint
        self._last_token: str | None = None

    def get_token(self, verbosity: int = 1) -> str:
        """Acquire a token. Tries silent → browser PKCE → device code."""

        # 1. Try silent with any cached account
        accounts = self._app.get_accounts(username=self._account_hint)
        if accounts:
            account = accounts[0]
            if verbosity >= 2:
                ink(f"  Trying silent auth for {account.get('username', '?')}...\n", Fore.WHITE + Style.DIM)
            result = self._app.acquire_token_silent(self._scopes, account=account)
            if result and "access_token" in result:
                if verbosity >= 2:
                    ink("  Using cached token\n", Fore.WHITE + Style.DIM)
                self._last_token = result["access_token"]
                return self._last_token
            elif verbosity >= 1:
                ink("  Silent auth failed, trying interactive...\n", Fore.YELLOW)

        # 2. Browser auth code flow with PKCE
        if verbosity >= 1:
            ink("  Opening browser for sign-in...\n", Fore.WHITE + Style.DIM)
        try:
            token = self._try_browser_auth(verbosity)
            return token
        except Exception as e:
            if verbosity >= 1:
                ink(f"  Browser auth failed: {e}\n", Fore.YELLOW)

        # 3. Device code flow (last resort)
        if verbosity >= 1:
            ink("  Falling back to device code login...\n", Fore.WHITE + Style.DIM)
        return self._try_device_code(verbosity)

    def ensure_fresh(self, verbosity: int = 0) -> str:
        """Silently refresh the token. Falls back to cached token."""
        accounts = self._app.get_accounts(username=self._account_hint)
        if accounts:
            result = self._app.acquire_token_silent(self._scopes, account=accounts[0])
            if result and "access_token" in result:
                self._last_token = result["access_token"]
                return self._last_token
            elif verbosity >= 1:
                ink("  Silent refresh failed\n", Fore.YELLOW)

        if self._last_token:
            return self._last_token
        raise RuntimeError("No token available. Run authentication first.")

    def cached_account(self) -> str | None:
        """Return the username of the first cached account, if any."""
        accounts = self._app.get_accounts(username=self._account_hint)
        if accounts:
            return accounts[0].get("username")
        return None

    def has_accounts(self) -> bool:
        return len(self._app.get_accounts()) > 0

    def sign_out_all(self) -> None:
        for account in self._app.get_accounts():
            self._app.remove_account(account)

    # ── Browser Auth Code (PKCE) ────────────────────────────────────

    def _try_browser_auth(self, verbosity: int) -> str:
        """Acquire token via browser-based auth code flow with PKCE."""
        # Bind a random port on localhost
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.bind(("127.0.0.1", 0))
        server_socket.listen(1)
        port = server_socket.getsockname()[1]
        redirect_uri = f"http://localhost:{port}"

        if verbosity >= 2:
            ink(f"  Redirect: {redirect_uri}\n", Fore.WHITE + Style.DIM)

        # Generate PKCE code verifier and challenge
        code_verifier = secrets.token_urlsafe(64)

        # Get the auth URL from MSAL
        flow = self._app.initiate_auth_code_flow(
            self._scopes,
            redirect_uri=redirect_uri,
            code_challenge_method="S256",
        )
        if "auth_uri" not in flow:
            raise RuntimeError(f"Failed to create auth flow: {flow.get('error_description', 'unknown error')}")

        auth_url = flow["auth_uri"]

        # Open browser
        webbrowser.open(auth_url)
        ink("  Waiting for sign-in in your browser...\n", Fore.WHITE + Style.DIM)

        # Wait for the redirect (2-minute timeout)
        server_socket.settimeout(120)
        try:
            conn, _ = server_socket.accept()
        except socket.timeout:
            server_socket.close()
            raise RuntimeError("Timed out waiting for browser sign-in")

        try:
            data = conn.recv(8192).decode("utf-8", errors="replace")

            # Extract the query string from the GET request
            first_line = data.split("\r\n")[0]  # e.g., "GET /?code=xxx&state=yyy HTTP/1.1"
            path = first_line.split(" ")[1] if len(first_line.split(" ")) > 1 else "/"
            query_string = urlparse(path).query
            params = parse_qs(query_string)

            # Check for error
            if "error" in params:
                error = params["error"][0]
                desc = params.get("error_description", [""])[0]
                raise RuntimeError(f"Authorization failed: {error} — {desc}")

            # Build auth_response dict for MSAL
            auth_response: dict[str, Any] = {}
            for key in params:
                auth_response[key] = params[key][0]

            # Send success page back to the browser
            html = (
                "<html><body style=\"font-family:system-ui;text-align:center;padding:60px\">"
                "<h2>Sign-in complete</h2>"
                "<p>You can close this tab and return to the terminal.</p>"
                "</body></html>"
            )
            response = (
                f"HTTP/1.1 200 OK\r\n"
                f"Content-Type: text/html\r\n"
                f"Content-Length: {len(html)}\r\n"
                f"Connection: close\r\n\r\n{html}"
            )
            conn.sendall(response.encode())
        finally:
            conn.close()
            server_socket.close()

        # Exchange authorization code for token
        result = self._app.acquire_token_by_auth_code_flow(flow, auth_response)

        if "access_token" not in result:
            error = result.get("error", "unknown")
            desc = result.get("error_description", "")
            raise RuntimeError(f"Token exchange failed: {error} — {desc}")

        self._last_token = result["access_token"]
        return self._last_token

    # ── Device Code Flow ────────────────────────────────────────────

    def _try_device_code(self, verbosity: int) -> str:
        """Acquire token via device code flow."""
        flow = self._app.initiate_device_flow(self._scopes)
        if "user_code" not in flow:
            raise RuntimeError(f"Device code flow failed: {flow.get('error_description', 'unknown error')}")

        print()
        ink(f"  {flow['message']}\n", Fore.YELLOW + Style.BRIGHT)
        ink(f"  Code: {flow['user_code']}  URL: {flow['verification_uri']}\n\n", Fore.GREEN + Style.BRIGHT)

        result = self._app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            error = result.get("error", "unknown")
            desc = result.get("error_description", "")
            raise RuntimeError(f"Device code auth failed: {error} — {desc}")

        self._last_token = result["access_token"]
        return self._last_token


# ── Token Decode ─────────────────────────────────────────────────────

def decode_token(token: str) -> None:
    """Decode and display key JWT claims (matching .NET / Rust CLI output)."""
    try:
        # Split and decode payload (no verification — just for display)
        parts = token.split(".")
        if len(parts) != 3:
            ink("  Token is not a valid JWT (expected 3 parts)\n", Fore.RED)
            return

        # Add padding for base64
        payload_b64 = parts[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        claims = json.loads(payload_bytes)

        for claim in ["aud", "appid", "app_displayname", "tid", "upn", "name", "scp"]:
            val = claims.get(claim)
            if val:
                print(f"  {claim:<16} {val}")

        exp = claims.get("exp")
        if exp:
            expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
            remaining = expires_at - datetime.now(tz=timezone.utc)
            remaining_mins = remaining.total_seconds() / 60

            time_str = f"{expires_at.strftime('%H:%M:%S')} UTC ({remaining_mins:.0f}m)" if remaining_mins > 0 else "EXPIRED"
            color = Fore.RED if remaining_mins < 5 else (Fore.WHITE + Style.DIM)
            ink(f"  {'expires':<16} {time_str}\n", color)
    except Exception as e:
        ink(f"  decode failed: {e}\n", Fore.RED)


# ── Utility ──────────────────────────────────────────────────────────

def ink(text: str, color: str) -> None:
    """Print colored text."""
    print(f"{color}{text}{Style.RESET_ALL}", end="")
