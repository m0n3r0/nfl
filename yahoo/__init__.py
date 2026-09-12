"""Yahoo Fantasy browser integration.

Mutating tools are deliberately split by workflow (read, lineup, waivers);
each is dry-run by default and fails closed on identity mismatch.
"""

from .cdp import CdpClient, CdpError, CdpJavaScriptError, CdpProtocolError

__all__ = ["CdpClient", "CdpError", "CdpJavaScriptError", "CdpProtocolError"]
