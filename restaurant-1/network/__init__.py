"""
Network package for Restaurant 1.
Contains the public MCP Server (for external wholesaler deliveries)
and the Wholesaler MCP Client (for outgoing CNP requests to H1/H2).
"""

from network.mcp_client import WholesalerMCPClient, default_mcp_client


def __getattr__(name: str):
    if name in ("mcp_server", "receive_delivery", "get_node_info"):
        import network.server as _server
        return getattr(_server, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "WholesalerMCPClient",
    "default_mcp_client",
    "mcp_server",
]
