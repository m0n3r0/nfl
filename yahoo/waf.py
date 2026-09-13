"""Shared detection for Yahoo's 'Request denied' WAF block page.

A blocked session is NOT a logged-out session: the cookies are fine, Yahoo's
WAF is throttling requests. Every reader should check this signature and fail
fast with a distinct error instead of multiplying requests into the block
(or, worse, reporting it as an auth expiry and inviting a pointless re-login).
"""

from __future__ import annotations

from typing import Any, Protocol


class WafClient(Protocol):
    def evaluate(self, expression: str) -> Any: ...


def denied(client: WafClient) -> bool:
    """True when the current page is Yahoo's 'Request denied' WAF block."""
    return bool(client.evaluate(
        "/* yahoo-waf-denied */ !!document.body && /Request denied/i.test(document.body.innerText)"))
