"""
Wholesaler MCP Client for Restaurant 1 (restaurant-1).
Connects to wholesaler MCP servers (e.g. H1 on port 8004, H2 on port 8005) via SSE,
requests price proposals (CALL_FOR_PROPOSAL -> PROPOSAL), and sends CNP decisions.
"""

import asyncio
import concurrent.futures
import json
import logging
from typing import Any, Dict, List, Optional

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client

from pathlib import Path
import sys

CURRENT_DIR = Path(__file__).resolve().parent
RESTAURANT_DIR = CURRENT_DIR.parent
if str(RESTAURANT_DIR) not in sys.path:
    sys.path.insert(0, str(RESTAURANT_DIR))
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

import config
from data.models import (
    AvailabilityRequestMessage,
    AvailabilityResponseMessage,
    ProposalMessage,
)

logger = logging.getLogger("restaurant-1.mcp_client")


def _run_async(coro):
    """Safely runs an async coroutine from synchronous context."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


class WholesalerMCPClient:
    """
    Client for interacting with Wholesaler MCP servers (H1, H2, ...).
    """

    def __init__(
        self,
        endpoints: Optional[Dict[str, str]] = None,
        timeout: float = config.MCP_CLIENT_TIMEOUT,
        llm_client: Optional[Any] = None,
    ):
        self.endpoints = endpoints or config.WHOLESALER_ENDPOINTS
        self.timeout = timeout
        self.llm_client = llm_client

    def _get_llm_client(self) -> Optional[Any]:
        """Returns initialized Gemini client or None."""
        if self.llm_client is not None:
            return self.llm_client
        if config.is_gemini_configured():
            try:
                from openai import OpenAI
                self.llm_client = OpenAI(
                    base_url=config.GEMINI_BASE_URL,
                    api_key=config.GEMINI_API_KEY,
                )
                return self.llm_client
            except Exception as e:
                logger.error(f"[MCP_CLIENT] Failed to initialize Gemini client: {e}")
                return None
        return None

    def _resolve_tool_with_llm(self, tools: List[Any], task_intent: str) -> Optional[str]:
        """
        Uses Gemini LLM to inspect tool names and descriptions on the MCP server
        and decide which tool matches the desired task intent.
        """
        client = self._get_llm_client()
        if not client:
            logger.warning("[MCP_CLIENT] Gemini client not configured; cannot inspect tool descriptions via LLM.")
            return None

        tools_info = []
        valid_names = set()
        for t in tools:
            name = getattr(t, "name", None) or (t.get("name") if isinstance(t, dict) else str(t))
            desc = getattr(t, "description", None) or (t.get("description") if isinstance(t, dict) else "")
            if name:
                valid_names.add(name)
                tools_info.append(f"- Nazwa: '{name}' | Opis: '{desc or 'Brak opisu'}'")

        if not tools_info:
            return None

        prompt = (
            f"Wybierasz narzędzie (tool) z zewnętrznego serwera MCP dla następującego zadania:\n"
            f"Zadanie: {task_intent}\n\n"
            f"Dostępne narzędzia na serwerze:\n"
            + "\n".join(tools_info)
            + "\n\n"
            f"Na podstawie nazw i opisów, która nazwa narzędzia najlepiej realizuje to zadanie?\n"
            f"Jeśli żadne narzędzie nie pasuje, odpowiedz słowem 'NONE'.\n"
            f"Odpowiedz WYŁĄCZNIE samą dokładną nazwą narzędzia (np. 'moje_narzedzie') lub 'NONE', bez żadnych dodatkowych słów, znaków ani formatowania."
        )

        try:
            logger.info(f"[MCP_CLIENT] Querying Gemini LLM to infer tool from descriptions for goal: '{task_intent}'...")
            model_to_use = getattr(config, "FALLBACK_MODEL", "gemini-3.1-flash-lite") or config.GEMINI_MODEL
            response = client.chat.completions.create(
                model=model_to_use,
                messages=[
                    {
                        "role": "system",
                        "content": "Jesteś precyzyjnym routerem narzędzi MCP. Wybierasz dokładnie jedną nazwę narzędzia z listy na podstawie opisu lub zwracasz NONE.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=500,
            )
            selected = response.choices[0].message.content.strip().strip("'\"` \n\t")
            if selected in valid_names:
                logger.info(f"[MCP_CLIENT] LLM resolved tool from description: '{selected}'")
                return selected
            elif selected.upper() == "NONE":
                logger.info(f"[MCP_CLIENT] LLM determined that no tool matches goal '{task_intent}'")
                return None
            else:
                for vn in valid_names:
                    if vn.lower() == selected.lower():
                        logger.info(f"[MCP_CLIENT] LLM resolved tool (case-insensitive): '{vn}'")
                        return vn
                logger.warning(f"[MCP_CLIENT] LLM returned unknown tool name: '{selected}'")
                return None
        except Exception as e:
            logger.error(f"[MCP_CLIENT] LLM tool resolution failed: {e}")
            return None

    async def check_availability_async(
        self, wholesaler_id: str, item_name: str, quantity: int
    ) -> Dict[str, Any]:
        """
        Asynchronously checks whether a wholesaler has the requested item quantity in stock.
        """
        # Attempt real MCP SSE connection
        url = self.endpoints.get(wholesaler_id)
        if not url:
            logger.warning(f"[MCP_CLIENT] No endpoint configured for wholesaler '{wholesaler_id}'")
            return {
                "sender_id": wholesaler_id,
                "receiver_id": config.AGENT_ID,
                "message_type": "AVAILABILITY_RESPONSE",
                "item": {"name": item_name, "quantity": quantity},
                "is_available": False,
                "available_quantity": 0,
                "error": "No endpoint configured",
            }

        logger.info(f"[MCP_CLIENT] Checking availability at {wholesaler_id} ({url})...")
        try:
            async with sse_client(url, timeout=self.timeout) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    tools_list = await session.list_tools()
                    tool_names = [t.name for t in tools_list.tools]

                    candidate_tools = [
                        "check_availability",
                        "get_availability",
                        "check_stock",
                        "query_stock",
                        "is_available",
                    ]
                    chosen_tool = next((t for t in candidate_tools if t in tool_names), None)

                    if not chosen_tool:
                        logger.info(
                            f"[MCP_CLIENT] None of candidate tool names found on {wholesaler_id}. "
                            "Checking tool descriptions on MCP server via LLM..."
                        )
                        chosen_tool = self._resolve_tool_with_llm(
                            tools=tools_list.tools,
                            task_intent="Sprawdzenie dostępności surowca i stanu magazynowego hurtowni (check item stock and availability)",
                        )

                    if not chosen_tool:
                        logger.warning(
                            f"[MCP_CLIENT] Wholesaler {wholesaler_id} does not expose availability tool."
                        )
                        return {
                            "sender_id": wholesaler_id,
                            "receiver_id": config.AGENT_ID,
                            "message_type": "AVAILABILITY_RESPONSE",
                            "item": {"name": item_name, "quantity": quantity},
                            "is_available": False,
                            "available_quantity": 0,
                            "error": "Availability tool not found on server",
                        }

                    tool_args = {
                        "item_name": item_name,
                        "quantity": quantity,
                        "sender_id": config.AGENT_ID,
                    }

                    result = await session.call_tool(chosen_tool, arguments=tool_args)
                    if not result.content:
                        return {
                            "sender_id": wholesaler_id,
                            "receiver_id": config.AGENT_ID,
                            "message_type": "AVAILABILITY_RESPONSE",
                            "item": {"name": item_name, "quantity": quantity},
                            "is_available": False,
                            "available_quantity": 0,
                            "error": "Empty tool response",
                        }

                    raw_text = result.content[0].text if hasattr(result.content[0], "text") else str(result.content[0])
                    avail_dict = json.loads(raw_text)
                    if "is_available" not in avail_dict and "available" in avail_dict:
                        avail_dict["is_available"] = bool(avail_dict["available"])
                    return avail_dict

        except Exception as e:
            logger.warning(
                f"[MCP_CLIENT] Availability check for {wholesaler_id} ({url}) failed: {e}"
            )
            return {
                "sender_id": wholesaler_id,
                "receiver_id": config.AGENT_ID,
                "message_type": "AVAILABILITY_RESPONSE",
                "item": {"name": item_name, "quantity": quantity},
                "is_available": False,
                "available_quantity": 0,
                "error": str(e),
            }

    async def check_all_availability_async(
        self, item_name: str, quantity: int, wholesaler_ids: Optional[List[str]] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Asynchronously checks stock availability across multiple wholesalers in parallel.
        Returns a mapping of wholesaler_id -> availability_dict.
        """
        targets = wholesaler_ids or list(self.endpoints.keys())
        tasks = [self.check_availability_async(w_id, item_name, quantity) for w_id in targets]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        availability_map: Dict[str, Dict[str, Any]] = {}
        for w_id, res in zip(targets, results):
            if isinstance(res, dict):
                availability_map[w_id] = res
            elif isinstance(res, Exception):
                logger.error(f"[MCP_CLIENT] Error checking availability for {w_id}: {res}")
                availability_map[w_id] = {
                    "sender_id": w_id,
                    "receiver_id": config.AGENT_ID,
                    "message_type": "AVAILABILITY_RESPONSE",
                    "item": {"name": item_name, "quantity": quantity},
                    "is_available": False,
                    "available_quantity": 0,
                    "error": str(res),
                }

        return availability_map

    async def fetch_quote_async(
        self, wholesaler_id: str, item_name: str, quantity: int
    ) -> Optional[Dict[str, Any]]:
        """
        Asynchronously connects to a wholesaler MCP server via SSE and requests a quote.
        """
        # Attempt real MCP SSE connection
        url = self.endpoints.get(wholesaler_id)
        if not url:
            logger.warning(f"[MCP_CLIENT] No endpoint configured for wholesaler '{wholesaler_id}'")
            return None

        logger.info(f"[MCP_CLIENT] Connecting to {wholesaler_id} at {url}...")
        try:
            async with sse_client(url, timeout=self.timeout) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    # Find appropriate tool name (e.g. request_quote, handle_call_for_proposal, get_quote)
                    tools_list = await session.list_tools()
                    tool_names = [t.name for t in tools_list.tools]

                    candidate_tools = [
                        "request_offer",
                        "get_price_proposal",
                        "request_quote",
                        "handle_call_for_proposal",
                        "create_quote",
                        "get_quote",
                    ]
                    chosen_tool = next((t for t in candidate_tools if t in tool_names), None)

                    if not chosen_tool:
                        logger.info(
                            f"[MCP_CLIENT] None of candidate tool names found on {wholesaler_id}. "
                            "Checking tool descriptions on MCP server via LLM..."
                        )
                        chosen_tool = self._resolve_tool_with_llm(
                            tools=tools_list.tools,
                            task_intent="Zapytanie o wycenę lub ofertę cenową na surowiec (request price quote or call for proposal for an item)",
                        )

                    if not chosen_tool:
                        logger.error(f"[MCP_CLIENT] No suitable quote tool found on {wholesaler_id}")
                        return None

                    tool_args = {
                        "item_name": item_name,
                        "quantity": quantity,
                        "sender_id": config.AGENT_ID,
                    }

                    result = await session.call_tool(chosen_tool, arguments=tool_args)

                    if not result.content:
                        logger.error(f"[MCP_CLIENT] Empty response from {wholesaler_id}")
                        return None

                    raw_text = result.content[0].text if hasattr(result.content[0], "text") else str(result.content[0])
                    proposal_dict = json.loads(raw_text)

                    # Validate format
                    ProposalMessage(**proposal_dict)
                    return proposal_dict

        except Exception as e:
            logger.warning(f"[MCP_CLIENT] Connection to {wholesaler_id} ({url}) failed: {e}")
            return None

    async def fetch_all_quotes_async(
        self, item_name: str, quantity: int, wholesaler_ids: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Asynchronously fetches quotes from all specified wholesalers in parallel.
        """
        targets = wholesaler_ids or list(self.endpoints.keys())
        tasks = [self.fetch_quote_async(w_id, item_name, quantity) for w_id in targets]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        valid_quotes: List[Dict[str, Any]] = []
        for w_id, res in zip(targets, results):
            if isinstance(res, dict):
                valid_quotes.append(res)
            elif isinstance(res, Exception):
                logger.error(f"[MCP_CLIENT] Error querying {w_id}: {res}")

        return valid_quotes

    async def send_decision_async(
        self, wholesaler_id: str, decision_msg: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Sends an ACCEPT_PROPOSAL (via accept_offer / accept_proposal / finalize_order) message to a wholesaler.
        Per A2A protocol, unselected offers silently expire without sending REJECT_PROPOSAL.
        Parses seller response to verify if seller accepted the order or rejected it (due to out-of-stock race condition).
        """
        url = self.endpoints.get(wholesaler_id)
        msg_type = decision_msg.get("message_type", "DECISION")

        if not url:
            return {"status": "ERROR", "message": f"No endpoint for {wholesaler_id}"}

        # Zgodnie z oficjalną specyfikacją protokołu A2A (zasada milczenia),
        # kupujący NIE wysyła REJECT_PROPOSAL do sprzedawców (oferty milcząco wygasają).
        if msg_type != "ACCEPT_PROPOSAL":
            logger.info(
                f"[MCP_CLIENT] Skipping sending {msg_type} to {wholesaler_id}: "
                "Per A2A protocol silent expiry, rejections are not sent to wholesalers."
            )
            return {
                "status": "SKIPPED",
                "wholesaler_id": wholesaler_id,
                "message_type": msg_type,
                "acknowledged": True,
                "message": "Silent expiry - no rejection sent to seller per A2A protocol.",
            }

        try:
            async with sse_client(url, timeout=self.timeout) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    tools_list = await session.list_tools()
                    tool_names = [t.name for t in tools_list.tools]

                    candidate_tools = ["accept_offer", "accept_proposal", "confirm_order", "finalize_order"]
                    chosen_tool = next((t for t in candidate_tools if t in tool_names), None)

                    if not chosen_tool:
                        logger.info(
                            f"[MCP_CLIENT] Candidate tool names not found on {wholesaler_id} for {msg_type}. "
                            "Checking tool descriptions on MCP server via LLM..."
                        )
                        chosen_tool = self._resolve_tool_with_llm(
                            tools=tools_list.tools,
                            task_intent="Złożenie zamówienia lub akceptacja oferty zakupu (accept_offer)",
                        )

                    if not chosen_tool:
                        chosen_tool = "accept_offer"

                    result = await session.call_tool(chosen_tool, arguments={"decision_data": decision_msg})

                    raw_text = (
                        result.content[0].text
                        if (result.content and hasattr(result.content[0], "text"))
                        else (str(result.content[0]) if result.content else "")
                    )

                    resp_dict: Dict[str, Any] = {}
                    if raw_text:
                        try:
                            resp_dict = json.loads(raw_text)
                        except Exception:
                            resp_dict = {"raw": raw_text}

                    is_reject = (
                        resp_dict.get("message_type") == "REJECT_PROPOSAL"
                        or resp_dict.get("status") in ("REJECTED", "ERROR", "OUT_OF_STOCK")
                        or resp_dict.get("rejected") is True
                    )

                    if is_reject:
                        logger.warning(
                            f"[MCP_CLIENT] Wholesaler {wholesaler_id} REJECTED accept_offer! Detail: {resp_dict}"
                        )
                        return {
                            "status": "REJECTED",
                            "wholesaler_id": wholesaler_id,
                            "message_type": "REJECT_PROPOSAL",
                            "response": resp_dict,
                            "acknowledged": False,
                            "reason": resp_dict.get("reason", "OUT_OF_STOCK"),
                        }
                    else:
                        logger.info(
                            f"[MCP_CLIENT] Wholesaler {wholesaler_id} accepted the order: {resp_dict}"
                        )
                        return {
                            "status": "ACCEPTED",
                            "wholesaler_id": wholesaler_id,
                            "message_type": resp_dict.get("message_type", "ACCEPT_PROPOSAL"),
                            "response": resp_dict,
                            "acknowledged": True,
                        }
        except Exception as e:
            logger.warning(f"[MCP_CLIENT] Could not send {msg_type} to {wholesaler_id}: {e}")
            return {
                "status": "NOTICE",
                "wholesaler_id": wholesaler_id,
                "message_type": msg_type,
                "acknowledged": False,
                "detail": str(e),
            }

    # Synchronous helper methods
    def check_availability(self, wholesaler_id: str, item_name: str, quantity: int) -> Dict[str, Any]:
        """Synchronous wrapper for check_availability_async."""
        return _run_async(self.check_availability_async(wholesaler_id, item_name, quantity))

    def check_all_availability(
        self, item_name: str, quantity: int, wholesaler_ids: Optional[List[str]] = None
    ) -> Dict[str, Dict[str, Any]]:
        """Synchronous wrapper for check_all_availability_async."""
        return _run_async(self.check_all_availability_async(item_name, quantity, wholesaler_ids))

    def fetch_quote(self, wholesaler_id: str, item_name: str, quantity: int) -> Optional[Dict[str, Any]]:
        """Synchronous wrapper for fetch_quote_async."""
        return _run_async(self.fetch_quote_async(wholesaler_id, item_name, quantity))

    def fetch_all_quotes(
        self, item_name: str, quantity: int, wholesaler_ids: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Synchronous wrapper for fetch_all_quotes_async."""
        return _run_async(self.fetch_all_quotes_async(item_name, quantity, wholesaler_ids))

    def send_decision(self, wholesaler_id: str, decision_msg: Dict[str, Any]) -> Dict[str, Any]:
        """Synchronous wrapper for send_decision_async."""
        return _run_async(self.send_decision_async(wholesaler_id, decision_msg))


# Global default client instance
default_mcp_client = WholesalerMCPClient()
