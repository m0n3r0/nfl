"""Yahoo Fantasy browser integration.

Mutating tools are deliberately split by workflow.  The mock-draft operator
cannot target the configured real league.
"""

from .cdp import CdpClient, CdpError, CdpJavaScriptError, CdpProtocolError

__all__ = ["CdpClient", "CdpError", "CdpJavaScriptError", "CdpProtocolError"]
