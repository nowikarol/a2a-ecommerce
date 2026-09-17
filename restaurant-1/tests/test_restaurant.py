"""
Unit and integration tests for Restaurant 1 (restaurant-1) MCP server and Groq Agent Brain.
Verifies Contract Net Protocol (CNP) compliance, SQL inventory logic with 11 Italian ingredients,
financial wallet balance tracking, Groq tools, and schema compatibility.
"""

import json
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch
import pytest

CURRENT_DIR = Path(__file__).resolve().parent
RESTAURANT_DIR = CURRENT_DIR.parent
if str(RESTAURANT_DIR) not in sys.path:
    sys.path.insert(0, str(RESTAURANT_DIR))

from data.models import (
    AcceptProposalMessage,
    AvailabilityRequestMessage,
    AvailabilityResponseMessage,
    CallForProposalMessage,
    DeliveryMessage,
    Item,
    ProposalMessage,
    RejectProposalMessage,
)
from network.server import mcp_server
from agent.tools import RestaurantAgent, GROQ_TOOLS, execute_tool
from agent.agent import RestaurantBrain, SYSTEM_PROMPT
from network.mcp_client import WholesalerMCPClient, default_mcp_client


class MockWholesalerMCPClient(WholesalerMCPClient):
    """Isolated test mock for WholesalerMCPClient used within tests."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mock_responses: Dict[str, Dict[str, Any]] = {}
        self._mock_availability: Dict[str, Dict[str, Any]] = {}
        self._mock_decision_responses: Dict[str, Dict[str, Any]] = {}

    def set_mock_response(self, wholesaler_id: str, proposal: Dict[str, Any]) -> None:
        self._mock_responses[wholesaler_id] = proposal

    def set_mock_availability(self, wholesaler_id: str, availability_data: Any) -> None:
        if isinstance(availability_data, bool):
            self._mock_availability[wholesaler_id] = {
                "sender_id": wholesaler_id,
                "receiver_id": "R1",
                "message_type": "AVAILABILITY_RESPONSE",
                "item": {"name": "mock", "quantity": 1},
                "is_available": availability_data,
                "available_quantity": 999 if availability_data else 0,
            }
        else:
            self._mock_availability[wholesaler_id] = availability_data

    def set_mock_decision_response(self, wholesaler_id: str, decision_data: Dict[str, Any]) -> None:
        self._mock_decision_responses[wholesaler_id] = decision_data

    def clear_mock_responses(self) -> None:
        self._mock_responses.clear()
        self._mock_availability.clear()
        self._mock_decision_responses.clear()

    async def check_availability_async(
        self, wholesaler_id: str, item_name: str, quantity: int
    ) -> Dict[str, Any]:
        if wholesaler_id in self._mock_availability:
            mock = dict(self._mock_availability[wholesaler_id])
            mock.setdefault("item", {"name": item_name, "quantity": quantity})
            return mock
        if wholesaler_id in self._mock_responses:
            return {
                "sender_id": wholesaler_id,
                "receiver_id": "R1",
                "message_type": "AVAILABILITY_RESPONSE",
                "item": {"name": item_name, "quantity": quantity},
                "is_available": True,
                "available_quantity": 9999,
            }
        return await super().check_availability_async(wholesaler_id, item_name, quantity)

    async def fetch_quote_async(
        self, wholesaler_id: str, item_name: str, quantity: int
    ) -> Optional[Dict[str, Any]]:
        if wholesaler_id in self._mock_responses:
            return self._mock_responses[wholesaler_id]
        return await super().fetch_quote_async(wholesaler_id, item_name, quantity)

    async def send_decision_async(
        self, wholesaler_id: str, decision_msg: Dict[str, Any]
    ) -> Dict[str, Any]:
        if wholesaler_id in self._mock_decision_responses:
            mock_res = self._mock_decision_responses[wholesaler_id]
            is_reject = (
                mock_res.get("message_type") == "REJECT_PROPOSAL"
                or mock_res.get("status") in ("REJECTED", "ERROR", "OUT_OF_STOCK")
                or mock_res.get("rejected") is True
            )
            status = "REJECTED" if is_reject else "ACCEPTED"
            return {
                "status": status,
                "wholesaler_id": wholesaler_id,
                "message_type": mock_res.get("message_type", "ACCEPT_PROPOSAL" if status == "ACCEPTED" else "REJECT_PROPOSAL"),
                "response": mock_res,
                "acknowledged": status == "ACCEPTED",
                "reason": mock_res.get("reason", "OUT_OF_STOCK" if is_reject else None),
            }
        if wholesaler_id in self._mock_responses:
            msg_type = decision_msg.get("message_type", "DECISION")
            return {
                "status": "ACCEPTED" if msg_type == "ACCEPT_PROPOSAL" else "SUCCESS",
                "wholesaler_id": wholesaler_id,
                "message_type": msg_type,
                "acknowledged": True,
            }
        return await super().send_decision_async(wholesaler_id, decision_msg)



@pytest.fixture
def temp_restaurant(tmp_path):
    """Creates an isolated restaurant agent with a fresh temporary SQLite database."""
    db_file = tmp_path / "test_restaurant.db"
    agent = RestaurantAgent(
        agent_id="R1",
        db_path=db_file,
        initial_balance=5000.0,
        currency="PLN",
    )
    return agent


class TestRestaurantModels:
    """Test schema compliance for CNP messages against docs/schemas/ specification."""

    def test_availability_request_structure(self):
        msg = AvailabilityRequestMessage(
            receiver_id="H1",
            item=Item(name="passata", quantity=50),
        )
        d = msg.to_dict()
        assert d["sender_id"] == "R1"
        assert d["receiver_id"] == "H1"
        assert d["message_type"] == "AVAILABILITY_REQUEST"
        assert d["item"] == {"name": "passata", "quantity": 50}
        assert "price" not in d["item"]

    def test_availability_response_structure(self):
        msg = AvailabilityResponseMessage(
            sender_id="H1",
            receiver_id="R1",
            item=Item(name="passata", quantity=50),
            is_available=True,
            available_quantity=300,
        )
        d = msg.to_dict()
        assert d["sender_id"] == "H1"
        assert d["receiver_id"] == "R1"
        assert d["message_type"] == "AVAILABILITY_RESPONSE"
        assert d["item"] == {"name": "passata", "quantity": 50}
        assert d["is_available"] is True
        assert d["available_quantity"] == 300

    def test_call_for_proposal_structure(self):
        msg = CallForProposalMessage(
            receiver_id="H1",
            item=Item(name="passata", quantity=100),
        )
        d = msg.to_dict()
        assert d["sender_id"] == "R1"
        assert d["receiver_id"] == "H1"
        assert d["message_type"] == "CALL_FOR_PROPOSAL"
        assert d["item"] == {"name": "passata", "quantity": 100}
        assert "price" not in d["item"]

    def test_proposal_structure(self):
        msg = ProposalMessage(
            sender_id="H1",
            receiver_id="R1",
            item=Item(name="passata", quantity=100, price=4.50),
            total_cost=450.00,
        )
        d = msg.to_dict()
        assert d["sender_id"] == "H1"
        assert d["receiver_id"] == "R1"
        assert d["message_type"] == "PROPOSAL"
        assert d["item"] == {"name": "passata", "quantity": 100, "price": 4.50}
        assert d["total_cost"] == 450.00

    def test_proposal_requires_price(self):
        with pytest.raises(ValueError):
            ProposalMessage(
                sender_id="H1",
                receiver_id="R1",
                item=Item(name="passata", quantity=100),
                total_cost=450.00,
            )

    def test_accept_proposal_structure(self):
        msg = AcceptProposalMessage(
            receiver_id="H1",
            item=Item(name="passata", quantity=100, price=4.50),
            total_cost=450.00,
        )
        d = msg.to_dict()
        assert d["sender_id"] == "R1"
        assert d["receiver_id"] == "H1"
        assert d["message_type"] == "ACCEPT_PROPOSAL"
        assert d["item"] == {"name": "passata", "quantity": 100, "price": 4.50}
        assert d["total_cost"] == 450.00

    def test_reject_proposal_structure(self):
        msg = RejectProposalMessage(
            receiver_id="H2",
            item=Item(name="passata", quantity=100),
        )
        d = msg.to_dict()
        assert d["sender_id"] == "R1"
        assert d["receiver_id"] == "H2"
        assert d["message_type"] == "REJECT_PROPOSAL"
        assert d["item"] == {"name": "passata", "quantity": 100}
        assert "price" not in d["item"]

    def test_delivery_message_structure(self):
        msg = DeliveryMessage(
            sender_id="H1",
            receiver_id="R1",
            item=Item(name="passata", quantity=50, price=4.50),
            total_cost=225.00,
        )
        d = msg.to_dict()
        assert d["sender_id"] == "H1"
        assert d["receiver_id"] == "R1"
        assert d["message_type"] == "DELIVERY"
        assert d["item"] == {"name": "passata", "quantity": 50, "price": 4.50}
        assert d["total_cost"] == 225.00


class TestRestaurantAgentSQLTools:
    """Test SQL-based tools and financial wallet provided by RestaurantAgent."""

    def test_check_inventory_and_11_ingredients(self, temp_restaurant):
        res = temp_restaurant.check_inventory()
        assert res["restaurant_id"] == "R1"
        assert res["total_items"] == 11
        assert res["wallet_balance"] == 5000.0
        assert res["currency"] == "PLN"

        expected_ingredients = [
            "flour",
            "passata",
            "mozzarella",
            "parmigiano reggiano",
            "burrata",
            "buffala",
            "prosciutto cotto",
            "prosciutto crudo",
            "arugula",
            "lamb's lettuce",
            "salami",
        ]
        for ing in expected_ingredients:
            assert ing in res["inventory"], f"Missing ingredient: {ing}"
            assert res["inventory"][ing]["quantity"] > 0
            assert res["inventory"][ing]["status"] == "OK"

    def test_get_financial_status(self, temp_restaurant):
        fin = temp_restaurant.get_financial_status()
        assert fin["status"] == "SUCCESS"
        assert fin["balance"] == 5000.0
        assert fin["currency"] == "PLN"
        assert len(fin["recent_transactions"]) >= 1

    def test_deposit_funds(self, temp_restaurant):
        dep = temp_restaurant.deposit_funds(1500.0, description="Additional capital")
        assert dep["status"] == "SUCCESS"
        assert dep["new_balance"] == 6500.0

        fin = temp_restaurant.get_financial_status()
        assert fin["balance"] == 6500.0

    def test_consume_ingredients_success(self, temp_restaurant):
        # margherita_classica requires: flour: 2, passata: 3, mozzarella: 2
        res = temp_restaurant.consume_ingredients("margherita_classica", 5)
        assert res["status"] == "SUCCESS"
        assert res["quantity_prepared"] == 5
        assert res["remaining_inventory"]["flour"] == 60 - (5 * 2)
        assert res["remaining_inventory"]["passata"] == 50 - (5 * 3)
        assert res["remaining_inventory"]["mozzarella"] == 40 - (5 * 2)

    def test_consume_ingredients_shortage(self, temp_restaurant):
        # pizza_diavola needs: salami: 2 per dish. Stock is 25. Ordering 20 needs 40 -> Shortage!
        res = temp_restaurant.consume_ingredients("pizza_diavola", 20)
        assert res["status"] == "SHORTAGE"
        assert len(res["shortages"]) > 0
        missing_items = {s["item_name"]: s["missing"] for s in res["shortages"]}
        assert "salami" in missing_items
        assert missing_items["salami"] == 15

        # Check that stock was untouched in SQL transaction
        inv = temp_restaurant.check_inventory()
        assert inv["inventory"]["salami"]["quantity"] == 25

    def test_consume_ingredients_threshold_breach(self, temp_restaurant):
        # passata initial: 50, safety_threshold: 20.
        # margherita_classica uses 3 passata. 12 dishes = 36 passata. 50 - 36 = 14 <= 20
        res = temp_restaurant.consume_ingredients("margherita_classica", 12)
        assert res["status"] == "SUCCESS"
        warning_items = [w["item_name"] for w in res["low_stock_warnings"]]
        assert "passata" in warning_items
        assert res["remaining_inventory"]["passata"] == 14

    def test_create_procurement_request(self, temp_restaurant):
        rfp = temp_restaurant.create_procurement_request(item_name="burrata", quantity=20, receiver_id="H1")
        assert rfp["sender_id"] == "R1"
        assert rfp["receiver_id"] == "H1"
        assert rfp["message_type"] == "CALL_FOR_PROPOSAL"
        assert rfp["item"] == {"name": "burrata", "quantity": 20}

    def test_evaluate_proposals_deterministic_min_cost_and_budget(self, temp_restaurant):
        proposals = [
            {
                "sender_id": "H1",
                "receiver_id": "R1",
                "message_type": "PROPOSAL",
                "item": {"name": "passata", "quantity": 50, "price": 6.00},
                "total_cost": 300.00,
            },
            {
                "sender_id": "H2",
                "receiver_id": "R1",
                "message_type": "PROPOSAL",
                "item": {"name": "passata", "quantity": 50, "price": 5.20},
                "total_cost": 260.00,
            },
        ]

        result = temp_restaurant.evaluate_proposals(proposals)
        assert result["status"] == "SUCCESS"
        assert result["winning_wholesaler"] == "H2"
        assert result["winning_total_cost"] == 260.00
        assert result["is_affordable"] is True
        assert result["current_wallet_balance"] == 5000.0

        accept = result["accept_proposal"]
        assert accept["receiver_id"] == "H2"
        assert accept["total_cost"] == 260.00

        rejects = result["reject_proposals"]
        # Zgodnie ze standardem protokołu A2A, pozostali sprzedawcy nie otrzymują wiadomości odrzucenia (oferty milcząco wygasają)
        assert len(rejects) == 0

    def test_receive_delivery_with_wallet_deduction(self, temp_restaurant):
        initial_stock = temp_restaurant.check_inventory()["inventory"]["passata"]["quantity"]
        initial_balance = temp_restaurant.get_financial_status()["balance"]

        del_res = temp_restaurant.receive_delivery(
            item_name="passata",
            quantity=30,
            supplier_id="H2",
            unit_price=5.00,
        )
        assert del_res["status"] == "DELIVERY_RECEIVED"
        assert del_res["new_stock_level"] == initial_stock + 30
        assert del_res["payment_deducted"] == 150.00
        assert del_res["remaining_wallet_balance"] == initial_balance - 150.00

        # Verify SQL state persistence
        fin = temp_restaurant.get_financial_status()
        assert fin["balance"] == initial_balance - 150.00

    def test_receive_delivery_from_wholesaler_schema(self, temp_restaurant):
        """Verify delivery incoming as external delivery.json document from wholesaler."""
        initial_stock = temp_restaurant.check_inventory()["inventory"]["burrata"]["quantity"]
        initial_balance = temp_restaurant.get_financial_status()["balance"]

        delivery_doc = {
            "sender_id": "H1",
            "receiver_id": "R1",
            "message_type": "DELIVERY",
            "item": {
                "name": "burrata",
                "quantity": 25,
                "price": 12.00,
            },
            "total_cost": 300.00,
        }

        del_res = temp_restaurant.receive_delivery(delivery_data=delivery_doc)
        assert del_res["status"] == "DELIVERY_RECEIVED"
        assert del_res["item_name"] == "burrata"
        assert del_res["quantity_received"] == 25
        assert del_res["supplier_id"] == "H1"
        assert del_res["payment_deducted"] == 300.00
        assert del_res["new_stock_level"] == initial_stock + 25
        assert del_res["remaining_wallet_balance"] == initial_balance - 300.00

    def test_receive_delivery_invalid_document_schema(self, temp_restaurant):
        """Verify that malformed or incorrect delivery document is rejected."""
        bad_doc = {
            "sender_id": "H1",
            "receiver_id": "R1",
            "message_type": "UNKNOWN_TYPE",
            "item": {"name": "flour"},
        }
        res = temp_restaurant.receive_delivery(delivery_data=bad_doc)
        assert res["status"] == "INVALID_DOCUMENT"

    def test_receive_delivery_insufficient_funds(self, temp_restaurant):
        # Attempt to order huge amount exceeding 5000 PLN budget
        del_res = temp_restaurant.receive_delivery(
            item_name="prosciutto crudo",
            quantity=500,
            supplier_id="H1",
            unit_price=100.00,  # 50,000 PLN > 5000 PLN
        )
        assert del_res["status"] == "INSUFFICIENT_FUNDS"

        # Verify stock and balance were untouched
        fin = temp_restaurant.get_financial_status()
        assert fin["balance"] == 5000.0

    def test_autonomous_procurement_trigger(self, temp_restaurant):
        # Update passata quantity below threshold via SQL
        conn = temp_restaurant.get_conn()
        try:
            with conn:
                conn.execute("UPDATE inventory SET quantity = 5 WHERE name = 'passata'")
        finally:
            conn.close()

        res = temp_restaurant.check_and_trigger_procurement(wholesalers=["H1", "H2"])
        assert res["status"] == "PROCUREMENT_TRIGGERED"
        assert "passata" in res["low_stock_items"]
        assert len(res["generated_rfps"]) == 1
        rfp_group = res["generated_rfps"][0]
        assert rfp_group["item_name"] == "passata"
        assert len(rfp_group["rfps"]) == 2


class TestGroqToolsAndBrain:
    """Test Groq tools specifications, dispatcher, and brain tool calling loop."""

    def test_groq_tools_specifications(self):
        assert len(GROQ_TOOLS) >= 7
        expected_names = {
            "check_inventory",
            "get_financial_status",
            "consume_ingredients",
            "check_wholesaler_availability",
            "create_procurement_request",
            "evaluate_proposals",
            "receive_delivery",
            "check_and_trigger_procurement",
        }
        actual_names = {t["function"]["name"] for t in GROQ_TOOLS}
        assert expected_names.issubset(actual_names)

    def test_execute_tool_dispatcher(self, temp_restaurant):
        # 1. check_inventory
        inv_str = execute_tool("check_inventory", {}, agent=temp_restaurant)
        inv = json.loads(inv_str)
        assert inv["restaurant_id"] == "R1"
        assert "passata" in inv["inventory"]
        assert "wallet_balance" in inv

        # 2. get_financial_status
        fin_str = execute_tool("get_financial_status", {}, agent=temp_restaurant)
        fin = json.loads(fin_str)
        assert fin["status"] == "SUCCESS"
        assert fin["balance"] == 5000.0

        # 3. create_procurement_request
        rfp_str = execute_tool(
            "create_procurement_request",
            {"item_name": "passata", "quantity": 100, "receiver_id": "H1"},
            agent=temp_restaurant,
        )
        rfp = json.loads(rfp_str)
        assert rfp["sender_id"] == "R1"
        assert rfp["receiver_id"] == "H1"
        assert rfp["message_type"] == "CALL_FOR_PROPOSAL"

        # 4. evaluate_proposals
        props = [
            {"sender_id": "H1", "receiver_id": "R1", "message_type": "PROPOSAL", "item": {"name": "passata", "quantity": 50, "price": 5.0}, "total_cost": 250.0},
            {"sender_id": "H2", "receiver_id": "R1", "message_type": "PROPOSAL", "item": {"name": "passata", "quantity": 50, "price": 4.5}, "total_cost": 225.0},
        ]
        eval_str = execute_tool("evaluate_proposals", {"proposals_list": props}, agent=temp_restaurant)
        eval_res = json.loads(eval_str)
        assert eval_res["winning_wholesaler"] == "H2"
        assert eval_res["winning_total_cost"] == 225.0

    def test_restaurant_brain_tool_calling_loop_mocked(self, temp_restaurant):
        """Mocks Groq API responses to verify the full tool calling loop execution."""
        mock_client = MagicMock()

        # Step 1: Model emits tool call for check_inventory
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_abc123"
        mock_tool_call.type = "function"
        mock_tool_call.function.name = "check_inventory"
        mock_tool_call.function.arguments = "{}"

        first_response = MagicMock()
        first_choice = MagicMock()
        first_choice.message.content = "Sprawdzam stan w bazie SQL..."
        first_choice.message.tool_calls = [mock_tool_call]
        first_response.choices = [first_choice]

        # Step 2: Model returns final answer after receiving tool result
        second_response = MagicMock()
        second_choice = MagicMock()
        second_choice.message.content = "W bazie SQL znajduje się 11 składników, a saldo wynosi 5000.00 PLN."
        second_choice.message.tool_calls = None
        second_response.choices = [second_choice]

        mock_client.chat.completions.create.side_effect = [first_response, second_response]

        brain = RestaurantBrain(api_key="mock_key_123", agent_backend=temp_restaurant)
        brain.client = mock_client

        history = brain.run_conversation([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Jaki jest stan spiżarni i portfela?"},
        ])

        assert len(history) == 5
        assert history[0]["role"] == "system"
        assert history[1]["role"] == "user"
        assert history[2]["role"] == "assistant"
        assert history[2]["tool_calls"][0]["function"]["name"] == "check_inventory"
        assert history[3]["role"] == "tool"
        assert history[3]["tool_call_id"] == "call_abc123"
        tool_content = json.loads(history[3]["content"])
        assert "inventory" in tool_content
        assert tool_content["wallet_balance"] == 5000.0
        assert history[4]["role"] == "assistant"
        assert "5000.00 PLN" in history[4]["content"]

    def test_restaurant_brain_mcp_quote_tool_calling_mocked(self, temp_restaurant, monkeypatch):
        """Verify RestaurantBrain can invoke request_quotes_and_evaluate and consume its result."""
        mock_client = MagicMock()

        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_mcp_quotes"
        mock_tool_call.function.name = "request_quotes_and_evaluate"
        mock_tool_call.function.arguments = json.dumps({"item_name": "burrata", "quantity": 10})

        first_response = MagicMock()
        first_choice = MagicMock()
        first_choice.message.content = "Odpytuję hurtownie H1 i H2 przez MCP..."
        first_choice.message.tool_calls = [mock_tool_call]
        first_response.choices = [first_choice]

        second_response = MagicMock()
        second_choice = MagicMock()
        second_choice.message.content = "Wybrano hurtownię H2 jako najtańszą (175.00 PLN)."
        second_choice.message.tool_calls = None
        second_response.choices = [second_choice]

        mock_client.chat.completions.create.side_effect = [first_response, second_response]

        brain = RestaurantBrain(api_key="mock_key_123", agent_backend=temp_restaurant)
        brain.client = mock_client

        mock_mcp = MockWholesalerMCPClient()
        monkeypatch.setattr("agent.tools.default_mcp_client", mock_mcp)

        mock_mcp.set_mock_response(
            "H1",
            {
                "sender_id": "H1",
                "receiver_id": "R1",
                "message_type": "PROPOSAL",
                "item": {"name": "burrata", "quantity": 10, "price": 18.50},
                "total_cost": 185.00,
            },
        )
        mock_mcp.set_mock_response(
            "H2",
            {
                "sender_id": "H2",
                "receiver_id": "R1",
                "message_type": "PROPOSAL",
                "item": {"name": "burrata", "quantity": 10, "price": 17.50},
                "total_cost": 175.00,
            },
        )
        history = brain.run_conversation([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Sprawdź oferty na 10 sztuk burraty."},
        ])

        assert len(history) == 5
        assert history[2]["tool_calls"][0]["function"]["name"] == "request_quotes_and_evaluate"
        tool_content = json.loads(history[3]["content"])
        assert tool_content["status"] == "SUCCESS"
        assert tool_content["winning_wholesaler"] in ("H1", "H2")
        assert "175.00 PLN" in history[4]["content"]


def test_mcp_server_tools_registered():
    """
    Weryfikacja separacji narzędzi (Separation of Concerns):
    Publiczny serwer MCP (A2A dla hurtowni) rejestruje WYŁĄCZNIE publiczne punkty styku:
    - receive_delivery (odbiór dostawy od hurtowni)
    - get_node_info (publiczne metadane węzła)

    Wszystkie prywatne narzędzia finansowe, magazynowe i zakupowe NIE MOGĄ być
    zarejestrowane na serwerze MCP, aby zapobiec wyciekowi danych do sieci!
    """
    import asyncio

    async def _check():
        tools = await mcp_server.list_tools()
        return [t.name for t in tools]

    tool_names = asyncio.run(_check())

    # 1. Publiczne narzędzia A2A muszą być zarejestrowane
    assert "receive_delivery" in tool_names, "receive_delivery missing from public MCP server"
    assert "get_node_info" in tool_names, "get_node_info missing from public MCP server"

    # 2. Narzędzia prywatne NIE MOGĄ być wystawione na publicznym serwerze MCP
    forbidden_public_tools = [
        "check_inventory",
        "get_financial_status",
        "deposit_funds",
        "consume_ingredients",
        "create_procurement_request",
        "evaluate_proposals",
        "check_and_trigger_procurement",
        "check_wholesaler_availability",
        "request_quotes_and_evaluate",
        "ask_restaurant_agent",
    ]
    for forbidden in forbidden_public_tools:
        assert forbidden not in tool_names, (
            f"Naruszenie bezpieczeństwa A2A: prywatne narzędzie '{forbidden}' jest wystawione na publicznym serwerze MCP!"
        )


def test_agent_groq_tools_complete():
    """
    Weryfikacja, że lokalny agent Groq (RestaurantBrain) nadal posiada pełen zestaw
    narzędzi biznesowych w GROQ_TOOLS do realizacji zadań i pętli decyzyjnych.
    """
    groq_tool_names = [t["function"]["name"] for t in GROQ_TOOLS]
    expected_agent_tools = [
        "check_inventory",
        "get_financial_status",
        "deposit_funds",
        "consume_ingredients",
        "create_procurement_request",
        "evaluate_proposals",
        "receive_delivery",
        "check_and_trigger_procurement",
        "check_wholesaler_availability",
        "request_quotes_and_evaluate",
    ]
    for req in expected_agent_tools:
        assert req in groq_tool_names, f"Narzędzie '{req}' brakuje w GROQ_TOOLS agenta"


def test_get_node_info(temp_restaurant):
    """Verify node info returns public identity."""
    info = temp_restaurant.get_node_info()
    assert info["status"] == "ONLINE"
    assert info["agent_id"] == "R1"
    assert "receive_delivery" in info["capabilities"]


class TestWholesalerMCPIntegration:
    """Tests for WholesalerMCPClient and the request_quotes_and_evaluate tool."""

    def test_wholesaler_mcp_client_offline_unreachable(self):
        """Verify that when wholesalers are offline/unreachable, no fake quotes are invented."""
        client = WholesalerMCPClient()
        quote = client.fetch_quote("H1", "flour", 50)
        assert quote is None
        quotes = client.fetch_all_quotes("flour", 50, wholesaler_ids=["H1", "H2"])
        assert quotes == []

    def test_wholesaler_mcp_client_custom_mock(self):
        client = MockWholesalerMCPClient()
        mock_h1 = {
            "sender_id": "H1",
            "receiver_id": "R1",
            "message_type": "PROPOSAL",
            "item": {"name": "burrata", "quantity": 10, "price": 19.00},
            "total_cost": 190.00,
        }
        mock_h2 = {
            "sender_id": "H2",
            "receiver_id": "R1",
            "message_type": "PROPOSAL",
            "item": {"name": "burrata", "quantity": 10, "price": 16.50},
            "total_cost": 165.00,
        }
        client.set_mock_response("H1", mock_h1)
        client.set_mock_response("H2", mock_h2)

        quotes = client.fetch_all_quotes("burrata", 10, ["H1", "H2"])
        assert len(quotes) == 2

        dec = client.send_decision("H2", {"message_type": "ACCEPT_PROPOSAL"})
        assert dec["status"] in ("ACCEPTED", "SUCCESS")
        assert dec["acknowledged"] is True

    def test_request_quotes_and_evaluate(self, temp_restaurant):
        """Verify request_quotes_and_evaluate selects min(total_cost) winner via MCP client."""
        client = MockWholesalerMCPClient()
        client.set_mock_response(
            "H1",
            {
                "sender_id": "H1",
                "receiver_id": "R1",
                "message_type": "PROPOSAL",
                "item": {"name": "mozzarella", "quantity": 20, "price": 15.00},
                "total_cost": 300.00,
            },
        )
        client.set_mock_response(
            "H2",
            {
                "sender_id": "H2",
                "receiver_id": "R1",
                "message_type": "PROPOSAL",
                "item": {"name": "mozzarella", "quantity": 20, "price": 13.50},
                "total_cost": 270.00,
            },
        )

        res = temp_restaurant.request_quotes_and_evaluate(
            item_name="mozzarella",
            quantity=20,
            wholesalers=["H1", "H2"],
            auto_order=False,
            mcp_client=client,
        )

        assert res["status"] == "SUCCESS"
        assert res["winning_wholesaler"] == "H2"
        assert res["winning_total_cost"] == 270.00
        assert res["is_affordable"] is True
        assert res["auto_order_dispatched"] is False

    def test_request_quotes_and_evaluate_auto_order(self, temp_restaurant):
        """Verify auto_order dispatches ACCEPT to winner and REJECT to loser."""
        client = MockWholesalerMCPClient()
        client.set_mock_response(
            "H1",
            {
                "sender_id": "H1",
                "receiver_id": "R1",
                "message_type": "PROPOSAL",
                "item": {"name": "passata", "quantity": 10, "price": 4.00},
                "total_cost": 40.00,
            },
        )
        client.set_mock_response(
            "H2",
            {
                "sender_id": "H2",
                "receiver_id": "R1",
                "message_type": "PROPOSAL",
                "item": {"name": "passata", "quantity": 10, "price": 5.00},
                "total_cost": 50.00,
            },
        )

        res = temp_restaurant.request_quotes_and_evaluate(
            item_name="passata",
            quantity=10,
            wholesalers=["H1", "H2"],
            auto_order=True,
            mcp_client=client,
        )

        assert res["status"] == "SUCCESS"
        assert res["winning_wholesaler"] == "H1"
        assert res["auto_order_dispatched"] is True
        # Zgodnie ze standardem wysyłana jest wyłącznie akceptacja do zwycięzcy (pozostali sprzedawcy nie otrzymują wiadomości)
        assert len(res["dispatched_decisions"]) == 1
        assert res["dispatched_decisions"][0]["wholesaler_id"] == "H1"
        assert res["dispatched_decisions"][0]["status"] == "ACCEPTED"

    def test_step4_fallback_when_winner_rejects_out_of_stock(self, temp_restaurant):
        """
        Krok 4 - Test Race Condition i Fallback:
        H1 zaoferowała niższą cenę (40 PLN) niż H2 (50 PLN).
        Jednak w Kroku 4, gdy restauracja wysyła accept_offer, H1 odrzuca (brak towaru).
        Restauracja automatycznie przechodzi do kolejnej oferty (H2) i skutecznie dokonuje zakupu.
        """
        client = MockWholesalerMCPClient()
        # Krok 1: Obie hurtownie mają towar podczas weryfikacji dostępności
        client.set_mock_availability("H1", True)
        client.set_mock_availability("H2", True)

        # Krok 2: Oferty cenowe (H1 tańsza: 40 PLN vs H2: 50 PLN)
        client.set_mock_response(
            "H1",
            {
                "sender_id": "H1",
                "receiver_id": "R1",
                "message_type": "PROPOSAL",
                "item": {"name": "passata", "quantity": 10, "price": 4.00},
                "total_cost": 40.00,
            },
        )
        client.set_mock_response(
            "H2",
            {
                "sender_id": "H2",
                "receiver_id": "R1",
                "message_type": "PROPOSAL",
                "item": {"name": "passata", "quantity": 10, "price": 5.00},
                "total_cost": 50.00,
            },
        )

        # Krok 4: H1 wyprzedała towar w międzyczasie i zwraca reject!
        client.set_mock_decision_response(
            "H1",
            {
                "sender_id": "H1",
                "receiver_id": "R1",
                "message_type": "REJECT_PROPOSAL",
                "item": {"name": "passata", "quantity": 10},
                "reason": "OUT_OF_STOCK",
            },
        )
        # H2 nadal posiada towar i akceptuje zamówienie
        client.set_mock_decision_response(
            "H2",
            {
                "sender_id": "H2",
                "receiver_id": "R1",
                "message_type": "ACCEPT_PROPOSAL",
                "item": {"name": "passata", "quantity": 10, "price": 5.00},
                "total_cost": 50.00,
            },
        )

        res = temp_restaurant.request_quotes_and_evaluate(
            item_name="passata",
            quantity=10,
            wholesalers=["H1", "H2"],
            auto_order=True,
            mcp_client=client,
        )

        assert res["status"] == "SUCCESS"
        # Ostatecznym zwycięzcą po fallbacku jest H2!
        assert res["winning_wholesaler"] == "H2"
        assert res["winning_total_cost"] == 50.00
        assert res["auto_order_dispatched"] is True
        assert res["order_status"] == "ACCEPTED"
        # Sprawdzenie historii decyzji: 1 odrzucona przez H1, 1 zaakceptowana przez H2
        assert len(res["dispatched_decisions"]) == 2
        assert res["dispatched_decisions"][0]["wholesaler_id"] == "H1"
        assert res["dispatched_decisions"][0]["status"] == "REJECTED"
        assert res["dispatched_decisions"][1]["wholesaler_id"] == "H2"
        assert res["dispatched_decisions"][1]["status"] == "ACCEPTED"

    def test_step4_all_sellers_reject_out_of_stock(self, temp_restaurant):
        """
        Krok 4: Gdy wszyscy dostępni oferenci odrzucą zamówienie z powodu braku towaru,
        restauracja oznacza status ALL_SELLERS_REJECTED i nie składa błędnego zamówienia.
        """
        client = MockWholesalerMCPClient()
        client.set_mock_availability("H1", True)
        client.set_mock_availability("H2", True)

        client.set_mock_response("H1", {
            "sender_id": "H1", "receiver_id": "R1", "message_type": "PROPOSAL",
            "item": {"name": "burrata", "quantity": 5, "price": 15.00}, "total_cost": 75.00,
        })
        client.set_mock_response("H2", {
            "sender_id": "H2", "receiver_id": "R1", "message_type": "PROPOSAL",
            "item": {"name": "burrata", "quantity": 5, "price": 16.00}, "total_cost": 80.00,
        })

        # Obie hurtownie odrzucają z powodu braku towaru w Kroku 4
        client.set_mock_decision_response("H1", {"message_type": "REJECT_PROPOSAL", "reason": "OUT_OF_STOCK"})
        client.set_mock_decision_response("H2", {"message_type": "REJECT_PROPOSAL", "reason": "OUT_OF_STOCK"})

        res = temp_restaurant.request_quotes_and_evaluate(
            item_name="burrata",
            quantity=5,
            wholesalers=["H1", "H2"],
            auto_order=True,
            mcp_client=client,
        )

        assert res["auto_order_dispatched"] is False
        assert res["order_status"] == "ALL_SELLERS_REJECTED"
        assert len(res["dispatched_decisions"]) == 2
        assert all(d["status"] == "REJECTED" for d in res["dispatched_decisions"])

    def test_execute_tool_request_quotes_and_evaluate(self, temp_restaurant, monkeypatch):
        """Verify tool execution dispatcher executes request_quotes_and_evaluate with mock."""
        mock_mcp = MockWholesalerMCPClient()
        monkeypatch.setattr("agent.tools.default_mcp_client", mock_mcp)

        mock_mcp.set_mock_response(
            "H1",
            {
                "sender_id": "H1",
                "receiver_id": "R1",
                "message_type": "PROPOSAL",
                "item": {"name": "burrata", "quantity": 5, "price": 18.00},
                "total_cost": 90.00,
            },
        )
        args_json = json.dumps({
            "item_name": "burrata",
            "quantity": 5,
            "wholesalers": ["H1"],
            "auto_order": False,
        })
        raw_res = execute_tool(
            name="request_quotes_and_evaluate",
            arguments=args_json,
            agent=temp_restaurant,
        )
        res = json.loads(raw_res)
        assert res["status"] == "SUCCESS"
        assert res["winning_wholesaler"] == "H1"
        assert res["winning_total_cost"] == 90.00

    def test_wholesaler_mcp_client_check_availability_offline(self):
        """Verify unreachable wholesaler returns is_available=False without artificial fallback."""
        client = WholesalerMCPClient()
        avail = client.check_all_availability("flour", 50, wholesaler_ids=["H1", "H2"])
        assert avail["H1"]["is_available"] is False
        assert avail["H1"]["available_quantity"] == 0
        assert avail["H2"]["is_available"] is False
        assert avail["H2"]["available_quantity"] == 0

    def test_wholesaler_mcp_client_check_availability_mock(self):
        """Verify custom mock availability works."""
        client = MockWholesalerMCPClient()
        client.set_mock_availability("H1", True)
        client.set_mock_availability("H2", False)

        avail = client.check_all_availability("passata", 50, wholesaler_ids=["H1", "H2"])
        assert avail["H1"]["is_available"] is True
        assert avail["H2"]["is_available"] is False

    def test_check_wholesaler_availability_agent_tool(self, temp_restaurant):
        """Verify RestaurantAgent.check_wholesaler_availability returns AVAILABLE or UNAVAILABLE."""
        client = MockWholesalerMCPClient()
        client.set_mock_availability("H1", True)
        client.set_mock_availability("H2", False)

        res_ok = temp_restaurant.check_wholesaler_availability(
            item_name="passata", quantity=20, mcp_client=client
        )
        assert res_ok["status"] == "AVAILABLE"
        assert res_ok["is_available"] is True
        assert len(res_ok["available_wholesalers"]) == 1
        assert res_ok["available_wholesalers"] == ["H1"]

        client.set_mock_availability("H1", False)
        res_none = temp_restaurant.check_wholesaler_availability(
            item_name="passata", quantity=99999, mcp_client=client
        )
        assert res_none["status"] == "UNAVAILABLE"
        assert res_none["is_available"] is False
        assert len(res_none["available_wholesalers"]) == 0

    def test_request_quotes_and_evaluate_aborts_when_unavailable(self, temp_restaurant):
        """
        Kluczowe wymaganie biznesowe:
        Jeśli produkt w żądanej ilości jest niedostępny w hurtowniach,
        proces zakupowy zostaje wstrzymany i zapytania o ceny NIE są wysyłane.
        """
        client = MockWholesalerMCPClient()
        # Mock obu hurtowni jako brak towaru
        client.set_mock_availability("H1", False)
        client.set_mock_availability("H2", False)

        res = temp_restaurant.request_quotes_and_evaluate(
            item_name="burrata",
            quantity=1000,
            wholesalers=["H1", "H2"],
            auto_order=False,
            mcp_client=client,
        )

        assert res["status"] == "UNAVAILABLE"
        assert res["quotes_requested"] is False
        assert res["available_wholesalers"] == []
        assert "niedostępny" in res["message"]
        assert "winning_wholesaler" not in res

    def test_request_quotes_and_evaluate_filters_unavailable_wholesalers(self, temp_restaurant):
        """
        Jeśli hurtownia H1 ma towar, a H2 nie ma, zapytanie cenowe jest wysyłane
        WYŁĄCZNIE do hurtowni H1 (nawet jeśli H2 miałaby tańszą ofertę w cenniku).
        """
        client = MockWholesalerMCPClient()
        client.set_mock_availability("H1", True)
        client.set_mock_availability("H2", False)

        client.set_mock_response(
            "H1",
            {
                "sender_id": "H1",
                "receiver_id": "R1",
                "message_type": "PROPOSAL",
                "item": {"name": "salami", "quantity": 10, "price": 40.00},
                "total_cost": 400.00,
            },
        )
        # H2 jest tańsza, ale nie ma towaru!
        client.set_mock_response(
            "H2",
            {
                "sender_id": "H2",
                "receiver_id": "R1",
                "message_type": "PROPOSAL",
                "item": {"name": "salami", "quantity": 10, "price": 20.00},
                "total_cost": 200.00,
            },
        )

        res = temp_restaurant.request_quotes_and_evaluate(
            item_name="salami",
            quantity=10,
            wholesalers=["H1", "H2"],
            auto_order=False,
            mcp_client=client,
        )

        assert res["status"] == "SUCCESS"
        assert res["quotes_requested"] is True
        assert res["available_wholesalers"] == ["H1"]
        # Wygrywa H1, bo tylko H1 miała towar na stanie
        assert res["winning_wholesaler"] == "H1"
        assert res["winning_total_cost"] == 400.00

    def test_execute_tool_check_wholesaler_availability(self, temp_restaurant):
        """Verify tool execution dispatcher executes check_wholesaler_availability."""
        args_json = json.dumps({
            "item_name": "passata",
            "quantity": 10,
            "wholesalers": ["H1", "H2"],
        })
        raw_res = execute_tool(
            name="check_wholesaler_availability",
            arguments=args_json,
            agent=temp_restaurant,
        )
        res = json.loads(raw_res)
        assert res["status"] in ("AVAILABLE", "UNAVAILABLE")
        assert "is_available" in res
        assert "available_wholesalers" in res

    def test_resolve_tool_with_llm_success(self):
        """Verify _resolve_tool_with_llm correctly picks tool based on description using mock LLM."""
        from unittest.mock import MagicMock

        class FakeTool:
            def __init__(self, name, description):
                self.name = name
                self.description = description

        tools = [
            FakeTool("random_other_tool", "Robi coś zupełnie innego"),
            FakeTool("check_wholesaler_warehouse_stock", "Sprawdza dostępność surowca w magazynie hurtowni"),
        ]

        mock_groq = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "check_wholesaler_warehouse_stock"
        mock_groq.chat.completions.create.return_value = mock_response

        client = WholesalerMCPClient(groq_client=mock_groq)
        chosen = client._resolve_tool_with_llm(
            tools=tools,
            task_intent="Sprawdzanie dostępności surowca",
        )
        assert chosen == "check_wholesaler_warehouse_stock"
        mock_groq.chat.completions.create.assert_called_once()

    def test_resolve_tool_with_llm_returns_none_when_no_match(self):
        """Verify _resolve_tool_with_llm returns None when LLM replies with NONE."""
        from unittest.mock import MagicMock

        class FakeTool:
            def __init__(self, name, description):
                self.name = name
                self.description = description

        tools = [
            FakeTool("print_invoice", "Drukarka faktur"),
        ]

        mock_groq = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "NONE"
        mock_groq.chat.completions.create.return_value = mock_response

        client = WholesalerMCPClient(groq_client=mock_groq)
        chosen = client._resolve_tool_with_llm(
            tools=tools,
            task_intent="Sprawdzanie dostępności surowca",
        )
        assert chosen is None

    def test_resolve_tool_with_llm_returns_none_when_unconfigured(self, monkeypatch):
        """Verify _resolve_tool_with_llm returns None if Groq is not configured."""
        import config
        monkeypatch.setattr(config, "GROQ_API_KEY", "")
        monkeypatch.setattr(config, "is_groq_configured", lambda: False)

        class FakeTool:
            def __init__(self, name, description):
                self.name = name
                self.description = description

        tools = [FakeTool("some_tool", "Opis")]
        client = WholesalerMCPClient(groq_client=None)
        chosen = client._resolve_tool_with_llm(tools=tools, task_intent="dowolny cel")
        assert chosen is None

    def test_resolve_tool_with_llm_rejects_hallucinated_tool_name(self):
        """Verify _resolve_tool_with_llm returns None if LLM returns a tool name not in server tools."""
        from unittest.mock import MagicMock

        class FakeTool:
            def __init__(self, name, description):
                self.name = name
                self.description = description

        tools = [FakeTool("actual_tool", "Opis actual tool")]
        mock_groq = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "invented_tool_that_does_not_exist"
        mock_groq.chat.completions.create.return_value = mock_response

        client = WholesalerMCPClient(groq_client=mock_groq)
        chosen = client._resolve_tool_with_llm(tools=tools, task_intent="dowolny cel")
        assert chosen is None


class TestAutoReorderAndConversationalMemory:
    """Tests verifying automated CNP reordering on stock depletion and conversation memory."""

    def test_consume_ingredients_auto_reorder_below_threshold(self, temp_restaurant):
        """Verify that when ingredient drops below safety threshold, auto_reorder triggers CNP purchase."""
        client = MockWholesalerMCPClient()
        client.set_mock_availability("H1", True)
        client.set_mock_availability("H2", True)
        client.set_mock_response(
            "H1",
            {
                "sender_id": "H1",
                "receiver_id": "R1",
                "message_type": "PROPOSAL",
                "item": {"name": "passata", "quantity": 36, "price": 4.50},
                "total_cost": 162.00,
            },
        )
        client.set_mock_response(
            "H2",
            {
                "sender_id": "H2",
                "receiver_id": "R1",
                "message_type": "PROPOSAL",
                "item": {"name": "passata", "quantity": 36, "price": 5.00},
                "total_cost": 180.00,
            },
        )

        # margherita_classica uses 3 passata. 12 * 3 = 36. Initial 50 -> 14 <= threshold (20)
        res = temp_restaurant.consume_ingredients(
            "margherita_classica",
            12,
            auto_reorder=True,
            mcp_client=client,
            wholesalers=["H1", "H2"],
        )

        assert res["status"] == "SUCCESS"
        assert "auto_reorders" in res
        assert len(res["auto_reorders"]) >= 1

        reorder = next(r for r in res["auto_reorders"] if r["item_name"] == "passata")
        assert reorder["reason"] == "SAFETY_THRESHOLD_BREACH"
        assert reorder["reorder_result"]["status"] == "SUCCESS"
        assert reorder["reorder_result"]["auto_order_dispatched"] is True
        assert reorder["reorder_result"]["winning_wholesaler"] == "H1"
        assert reorder["reorder_result"]["winning_total_cost"] == 162.00

    def test_consume_ingredients_auto_reorder_shortage(self, temp_restaurant):
        """Verify that when ingredient shortage occurs, auto_reorder triggers procurement for deficit."""
        client = MockWholesalerMCPClient()
        client.set_mock_availability("H1", True)
        client.set_mock_response(
            "H1",
            {
                "sender_id": "H1",
                "receiver_id": "R1",
                "message_type": "PROPOSAL",
                "item": {"name": "salami", "quantity": 30, "price": 8.00},
                "total_cost": 240.00,
            },
        )

        # pizza_diavola uses 2 salami per dish. 20 dishes need 40 salami. Initial stock = 25 -> Shortage!
        res = temp_restaurant.consume_ingredients(
            "pizza_diavola",
            20,
            auto_reorder=True,
            mcp_client=client,
            wholesalers=["H1"],
        )

        assert res["status"] == "SHORTAGE"
        assert "auto_reorders" in res
        assert len(res["auto_reorders"]) >= 1

        salami_order = next(r for r in res["auto_reorders"] if r["item_name"] == "salami")
        assert salami_order["reason"] == "SHORTAGE"
        assert salami_order["reorder_result"]["status"] == "SUCCESS"
        assert salami_order["reorder_result"]["auto_order_dispatched"] is True
        assert salami_order["reorder_result"]["winning_wholesaler"] == "H1"

    def test_consume_ingredients_auto_reorder_disabled(self, temp_restaurant):
        """Verify that when auto_reorder=False, no procurement order is dispatched."""
        res = temp_restaurant.consume_ingredients(
            "margherita_classica",
            12,
            auto_reorder=False,
        )

        assert res["status"] == "SUCCESS"
        assert "auto_reorders" not in res
        assert len(res["low_stock_warnings"]) >= 1
        assert "passata" in [w["item_name"] for w in res["low_stock_warnings"]]

    def test_restaurant_brain_conversational_memory_sliding_window(self, temp_restaurant):
        """Verify RestaurantBrain maintains up to 4 recent messages and slides window correctly."""
        mock_groq = MagicMock()

        def make_reply(text):
            m = MagicMock()
            choice = MagicMock()
            choice.message.content = text
            choice.message.tool_calls = None
            m.choices = [choice]
            return m

        mock_groq.chat.completions.create.side_effect = [
            make_reply("Mamy 40 kg mozzarelli."),
            make_reply("Do margherity potrzebujemy 2 kg sera."),
            make_reply("Przygotowano 3 pizze margherita."),
        ]

        brain = RestaurantBrain(
            api_key="mock_key_test",
            agent_backend=temp_restaurant,
            max_memory_messages=4,
        )
        brain.client = mock_groq

        # Turn 1
        reply1 = brain.ask("Ile mamy mozzarelli?")
        assert reply1 == "Mamy 40 kg mozzarelli."
        mem1 = brain.get_memory()
        assert len(mem1) == 2
        assert mem1[0] == {"role": "user", "content": "Ile mamy mozzarelli?"}
        assert mem1[1] == {"role": "assistant", "content": "Mamy 40 kg mozzarelli."}

        # Turn 2
        reply2 = brain.ask("A ile sera idzie na margheritę?")
        assert reply2 == "Do margherity potrzebujemy 2 kg sera."
        mem2 = brain.get_memory()
        assert len(mem2) == 4

        # Turn 3 -> sliding window should drop Turn 1 and keep Turn 2 + Turn 3 (4 messages)
        reply3 = brain.ask("To przygotuj 3 pizze")
        assert reply3 == "Przygotowano 3 pizze margherita."
        mem3 = brain.get_memory()
        assert len(mem3) == 4
        assert mem3[0] == {"role": "user", "content": "A ile sera idzie na margheritę?"}
        assert mem3[1] == {"role": "assistant", "content": "Do margherity potrzebujemy 2 kg sera."}
        assert mem3[2] == {"role": "user", "content": "To przygotuj 3 pizze"}
        assert mem3[3] == {"role": "assistant", "content": "Przygotowano 3 pizze margherita."}

    def test_restaurant_brain_clear_memory(self, temp_restaurant):
        """Verify clear_memory empties the conversation memory."""
        mock_groq = MagicMock()
        choice = MagicMock()
        choice.message.content = "Jasne!"
        choice.message.tool_calls = None
        mock_resp = MagicMock()
        mock_resp.choices = [choice]
        mock_groq.chat.completions.create.return_value = mock_resp

        brain = RestaurantBrain(api_key="mock_key_test", agent_backend=temp_restaurant)
        brain.client = mock_groq

        brain.ask("Cześć!")
        assert len(brain.get_memory()) == 2

        brain.clear_memory()
        assert brain.get_memory() == []




