"""
Public B2B/A2A MCP Server for Restaurant 1 (restaurant-1).
Exposes only secure public endpoints for peer trading partners (Wholesalers)
in the Contract Net Protocol (CNP) multi-agent supply chain.

Internal tools (financial wallet, pantry management, procurement logic)
remain strictly private to the local agent brain (agent/tools.py) and are not exposed.
"""

import argparse
import logging
from pathlib import Path
import sys
from typing import Any, Dict

# Set up logging to stderr so stdio MCP transport is not corrupted
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, stream=sys.stderr)
logger = logging.getLogger("restaurant-1.server")

# MCP Server Import (Supports both MCP 2.x and 1.x)
try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    from mcp.server.fastmcp import FastMCP as MCPServer

# Relative imports from restaurant-1
CURRENT_DIR = Path(__file__).resolve().parent
RESTAURANT_DIR = CURRENT_DIR.parent
if str(RESTAURANT_DIR) not in sys.path:
    sys.path.insert(0, str(RESTAURANT_DIR))
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

import config

mcp_server = MCPServer("restaurant-1")


def _get_agent():
    """Helper to lazily retrieve RestaurantAgent instance and avoid circular imports."""
    from agent.tools import default_agent
    return default_agent


@mcp_server.tool()
def receive_delivery(delivery_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Publiczny punkt styku B2B dla Hurtowni (dostawcy towaru):
    Odbiera sformatowany dokument DELIVERY zgodny z docs/schemas/json-schemas/delivery.json.
    Waliduje dokument dostawy, przyjmuje towar do bazy SQL oraz rozlicza płatność z portfela restauracji.
    """
    logger.info(f"[MCP:A2A] Otrzymano żądanie dostawy od kontrahenta: {delivery_data.get('sender_id')}")
    return _get_agent().receive_delivery(delivery_data=delivery_data)


@mcp_server.tool()
def get_node_info() -> Dict[str, Any]:
    """
    Zwraca publiczną tożsamość węzła handlowego Restauracji 1 w sieci A2A / CNP.
    """
    return _get_agent().get_node_info()


def main():
    parser = argparse.ArgumentParser(description="Restaurant 1 Public A2A MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="MCP transport protocol (default: stdio)",
    )
    parser.add_argument("--port", type=int, default=8011, help="Port for SSE/HTTP transports (default: 8011)")
    args = parser.parse_args()

    logger.info(f"[restaurant-1] Starting public A2A MCP server on transport='{args.transport}' (port={args.port})...")
    if args.transport == "stdio":
        mcp_server.run(transport="stdio")
    elif args.transport == "sse":
        mcp_server.run(transport="sse", port=args.port)
    elif args.transport == "streamable-http":
        mcp_server.run(transport="streamable-http", port=args.port)


if __name__ == "__main__":
    main()
