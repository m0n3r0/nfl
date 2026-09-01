"""Strict, loopback-only Chrome DevTools Protocol transport."""

from __future__ import annotations

import json
import socket
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

import websocket


class CdpError(RuntimeError):
    """Base exception for deterministic CDP failures."""


class CdpProtocolError(CdpError):
    """A CDP command returned an explicit protocol error."""


class CdpJavaScriptError(CdpError):
    """Runtime.evaluate reported a JavaScript exception."""


class CdpTimeout(CdpError):
    """A CDP request exceeded its deadline."""


@dataclass(frozen=True)
class Target:
    """A browser target returned by the CDP HTTP endpoint."""

    id: str
    type: str
    title: str
    url: str
    websocket_url: str


def _require_loopback(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("CDP endpoint must be HTTP on loopback")
    return endpoint.rstrip("/")


def _require_loopback_websocket(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"ws", "wss"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("CDP websocket URL must use ws/wss on loopback")
    return url


def list_targets(endpoint: str = "http://127.0.0.1:9222", timeout: float = 8) -> list[Target]:
    """Read page targets from a loopback CDP endpoint."""
    endpoint = _require_loopback(endpoint)
    with urllib.request.urlopen(endpoint + "/json/list", timeout=timeout) as response:
        rows = json.load(response)
    return [
        Target(
            id=str(row.get("id", "")),
            type=str(row.get("type", "")),
            title=str(row.get("title", "")),
            url=str(row.get("url", "")),
            websocket_url=str(row.get("webSocketDebuggerUrl", "")),
        )
        for row in rows
        if row.get("webSocketDebuggerUrl")
    ]


def select_target(
    predicate: Callable[[Target], bool],
    endpoint: str = "http://127.0.0.1:9222",
) -> Target:
    """Return exactly one matching page target; ambiguity fails closed."""
    matches = [target for target in list_targets(endpoint) if target.type == "page" and predicate(target)]
    if len(matches) != 1:
        raise CdpError(f"expected exactly one matching page target, found {len(matches)}")
    return matches[0]


class CdpClient:
    """Synchronous CDP client with monotonic IDs, deadlines, and typed errors."""

    def __init__(self, target: Target, endpoint: str = "http://127.0.0.1:9222", timeout: float = 12):
        self.endpoint = _require_loopback(endpoint)
        self.target = target
        self.timeout = timeout
        self._next_id = 0
        try:
            self._ws = websocket.create_connection(
                _require_loopback_websocket(target.websocket_url),
                timeout=timeout,
                origin=self.endpoint,
            )
        except (OSError, websocket.WebSocketException) as exc:
            raise CdpError(f"CDP websocket connection failed: {exc}") from exc

    def __enter__(self) -> "CdpClient":
        try:
            self.call("Runtime.enable")
            self.call("Page.enable")
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the target websocket."""
        self._ws.close()

    def call(self, method: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> dict[str, Any]:
        """Execute one CDP command and return its result object."""
        self._next_id += 1
        message_id = self._next_id
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        try:
            self._ws.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        except (OSError, websocket.WebSocketException) as exc:
            raise CdpError(f"{method} send failed: {exc}") from exc
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CdpTimeout(f"{method} timed out")
            self._ws.settimeout(remaining)
            try:
                reply = json.loads(self._ws.recv())
            except (socket.timeout, websocket.WebSocketTimeoutException) as exc:
                raise CdpTimeout(f"{method} timed out") from exc
            except (OSError, websocket.WebSocketException, json.JSONDecodeError) as exc:
                raise CdpError(f"{method} receive failed: {exc}") from exc
            if reply.get("id") != message_id:
                continue
            if "error" in reply:
                error = reply["error"]
                raise CdpProtocolError(f"{method}: {error.get('code')}: {error.get('message')}")
            return reply.get("result", {})

    def evaluate(self, expression: str, timeout: float | None = None) -> Any:
        """Evaluate JavaScript by value and raise on JavaScript exceptions."""
        result = self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
            timeout=timeout,
        )
        if result.get("exceptionDetails"):
            details = result["exceptionDetails"]
            description = details.get("exception", {}).get("description") or details.get("text") or "JavaScript exception"
            raise CdpJavaScriptError(description)
        return result.get("result", {}).get("value")

    def bring_to_front(self) -> None:
        """Foreground the connected page target."""
        self.call("Page.bringToFront")

    def navigate(self, url: str, expected: Callable[[str], bool], timeout: float = 20) -> str:
        """Navigate and wait for both DOM readiness and an expected final URL."""
        self.call("Page.navigate", {"url": url})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.evaluate("({url: location.href, ready: document.readyState})")
            if state and state["ready"] in {"interactive", "complete"} and expected(state["url"]):
                return state["url"]
            time.sleep(0.1)
        raise CdpTimeout("navigation did not reach the expected page")
