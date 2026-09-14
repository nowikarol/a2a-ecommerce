"""
Wholesaler MCP Client for Restaurant 1 (restaurant-1).
Connects to wholesaler MCP servers (e.g. H1 on port 8001, H2 on port 8002) via SSE,
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
        groq_client: Optional[Any] = None,
    ):
        self.endpoints = endpoints or config.WHOLESALER_ENDPOINTS
        self.timeout = timeout
        self.groq_client = groq_client
        self._mock_responses: Dict[str, Dict[str, Any]] = {}
        self._mock_availability: Dict[str, Dict[str, Any]] = {}
        self._mock_decision_responses: Dict[str, Dict[str, Any]] = {}

    def _get_groq_client(self) -> Optional[Any]:
        """Returns initialized Groq client or None."""
        if self.groq_client is not None:
            return self.groq_client
        if config.is_groq_configured():
            try:
                from groq import Groq
                return Groq(api_key=config.GROQ_API_KEY)
            except Exception as e:
                logger.error(f"[MCP_CLIENT] Failed to initialize Groq client: {e}")
                return None
        return None

    def _resolve_tool_with_llm(self, tools: List[Any], task_intent: str) -> Optional[str]:
        """
        Uses Groq LLM to inspect tool names and descriptions on the MCP server
        and decide which tool matches the desired task intent.
        """
        client = self._get_groq_client()
        if not client:
            logger.warning("[MCP_CLIENT] Groq client not configured; cannot inspect tool descriptions via LLM.")
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
            logger.info(f"[MCP_CLIENT] Querying LLM to infer tool from descriptions for goal: '{task_intent}'...")
            model_to_use = getattr(config, "FALLBACK_MODEL", "llama-3.1-8b-instant") or config.GROQ_MODEL
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

    def set_mock_response(self, wholesaler_id: str, proposal: Dict[str, Any]) -> None:
        """Sets a mock proposal for testing."""
        self._mock_responses[wholesaler_id] = proposal

    def set_mock_availability(self, wholesaler_id: str, availability_data: Any) -> None:
        """Sets a mock availability response for testing."""
        if isinstance(availability_data, bool):
            self._mock_availability[wholesaler_id] = {
                "sender_id": wholesaler_id,
                "receiver_id": config.AGENT_ID,
                "message_type": "AVAILABILITY_RESPONSE",
                "item": {"name": "mock", "quantity": 1},
                "is_available": availability_data,
                "available_quantity": 999 if availability_data else 0,
            }
        else:
            self._mock_availability[wholesaler_id] = availability_data

    def set_mock_decision_response(self, wholesaler_id: str, decision_data: Dict[str, Any]) -> None:
        """Sets a mock response to an accept_offer/decision call for testing Step 4."""
        self._mock_decision_responses[wholesaler_id] = decision_data

    def clear_mock_responses(self) -> None:
        """Clears all registered mock responses, availability, and decisions."""
        self._mock_responses.clear()
        self._mock_availability.clear()
        self._mock_decision_responses.clear()

    async def check_availability_async(
        self, wholesaler_id: str, item_name: str, quantity: int
    ) -> Dict[str, Any]:
        """
        Asynchronously checks whether a wholesaler has the requested item quantity in stock.
        """
        # 1. Check if an explicit mock availability response is configured (for unit testing)
        if wholesaler_id in self._mock_availability:
            logger.info(f"[MCP_CLIENT] Using registered mock availability for {wholesaler_id}")
            mock = dict(self._mock_availability[wholesaler_id])
            mock.setdefault("item", {"name": item_name, "quantity": quantity})
            return mock

        # If a mock proposal is registered for this wholesaler in test context, treat as available
        if wholesaler_id in self._mock_responses:
            return {
                "sender_id": wholesaler_id,
                "receiver_id": config.AGENT_ID,
                "message_type": "AVAILABILITY_RESPONSE",
                "item": {"name": item_name, "quantity": quantity},
                "is_available": True,
                "available_quantity": 9999,
            }

        # 2. Attempt real MCP SSE connection
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
        # 1. Check if an explicit mock response is configured (for unit tests)
        if wholesaler_id in self._mock_responses:
            logger.info(f"[MCP_CLIENT] Using registered mock response for {wholesaler_id}")
            return self._mock_responses[wholesaler_id]

        # 2. Attempt real MCP SSE connection
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
        Sends an ACCEPT_PROPOSAL (via accept_offer / accept_proposal) or REJECT_PROPOSAL message to a wholesaler.
        Parses seller response to verify if seller accepted the order or rejected it (due to out of stock).
        """
        url = self.endpoints.get(wholesaler_id)
        msg_type = decision_msg.get("message_type", "DECISION")

        # 1. Explicit mock decision response (for testing step 4 accept vs reject)
        if wholesaler_id in self._mock_decision_responses:
            mock_res = self._mock_decision_responses[wholesaler_id]
            is_reject = (
                mock_res.get("message_type") == "REJECT_PROPOSAL"
                or mock_res.get("status") in ("REJECTED", "ERROR", "OUT_OF_STOCK")
                or mock_res.get("rejected") is True
            )
            status = "REJECTED" if is_reject else "ACCEPTED"
            logger.info(f"[MCP_CLIENT] Returning mock decision response for {wholesaler_id}: {status}")
            return {
                "status": status,
                "wholesaler_id": wholesaler_id,
                "message_type": mock_res.get("message_type", "ACCEPT_PROPOSAL" if status == "ACCEPTED" else "REJECT_PROPOSAL"),
                "response": mock_res,
                "acknowledged": status == "ACCEPTED",
                "reason": mock_res.get("reason", "OUT_OF_STOCK" if is_reject else None),
            }

        # 2. General mock fallback for test compatibility
        if wholesaler_id in self._mock_responses:
            logger.info(f"[MCP_CLIENT] Sent {msg_type} to mock {wholesaler_id}: {decision_msg}")
            return {
                "status": "ACCEPTED" if msg_type == "ACCEPT_PROPOSAL" else "SUCCESS",
                "wholesaler_id": wholesaler_id,
                "message_type": msg_type,
                "acknowledged": True,
            }

        if not url:
            return {"status": "ERROR", "message": f"No endpoint for {wholesaler_id}"}

        try:
            async with sse_client(url, timeout=self.timeout) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    tools_list = await session.list_tools()
                    tool_names = [t.name for t in tools_list.tools]

                    if msg_type == "ACCEPT_PROPOSAL":
                        candidate_tools = ["accept_offer", "accept_proposal", "confirm_order"]
                    else:
                        candidate_tools = ["reject_proposal", "reject_offer"]

                    chosen_tool = next((t for t in candidate_tools if t in tool_names), None)

                    if not chosen_tool:
                        logger.info(
                            f"[MCP_CLIENT] Candidate tool names not found on {wholesaler_id} for {msg_type}. "
                            "Checking tool descriptions on MCP server via LLM..."
                        )
                        chosen_tool = self._resolve_tool_with_llm(
                            tools=tools_list.tools,
                            task_intent=f"Złożenie zamówienia lub przekazanie decyzji zakupowej ({msg_type})",
                        )

                    if not chosen_tool:
                        chosen_tool = "accept_offer" if msg_type == "ACCEPT_PROPOSAL" else "reject_proposal"

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
