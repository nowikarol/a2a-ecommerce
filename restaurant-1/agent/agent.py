"""
Groq API-powered Agent Brain for Restaurant 1 (restaurant-1).
Implements LLM tool-calling loop using Groq SDK and maps results to docs/schemas/.
"""

import argparse
import json
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

from groq import Groq

CURRENT_DIR = Path(__file__).resolve().parent
RESTAURANT_DIR = CURRENT_DIR.parent
if str(RESTAURANT_DIR) not in sys.path:
    sys.path.insert(0, str(RESTAURANT_DIR))
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

import config
from agent.tools import GROQ_TOOLS, RestaurantAgent, default_agent, execute_tool

logger = logging.getLogger("restaurant-1.agent")

SYSTEM_PROMPT = """Jesteś autonomicznym agentem Restauracji nr 1 (identyfikator: R1) w architekturze łańcucha dostaw multi-agentowego (MAS: Producent – Hurtownie – Restauracje). Twoja baza danych oparta jest na relacyjnej bazie SQLite i natywnych zapytaniach SQL.

Twoje zadania i zasady działania:
1. Zarządzanie spiżarnią i baza składników w SQL:
   - Monitorujesz stan magazynowy 11 surowców: flour, passata, mozzarella, parmigiano reggiano, burrata, buffala, prosciutto cotto, prosciutto crudo, arugula, lamb's lettuce, salami za pomocą narzędzia `check_inventory`.
   - Każdy składnik w bazie posiada zdefiniowany próg bezpieczeństwa (safety_threshold) oraz wielkość domyślnego uzupełnienia (reorder_quantity).
2. Obsługa potraw i receptur:
   - Realizujesz zamówienia kuchenne (np. margherita_classica, pizza_diavola, pizza_bufala, pizza_parma_arugula, pizza_prosciutto_cotto, insalata_burrata, tagliere_italiano) odejmując składniki narzędziem `consume_ingredients`.
   - W przypadku braku surowców natychmiast raportujesz braki i przystępujesz do zaopatrzenia.
3. Kontrola finansowa i budżet zakupowy:
   - Restauracja dysponuje portfelem finansowym w walucie PLN, który sprawdzasz narzędziem `get_financial_status`.
   - Przed podjęciem decyzji o zakupie weryfikujesz, czy koszt oferty nie przekracza dostępnego salda środków.
4. Protokół Contract Net Protocol (CNP) i komunikacja MCP:
   - Dwuetapowy proces zakupowy: przed wysłaniem zapytań o ceny weryfikujesz dostępność danej ilości surowca w hurtowniach (narzędziem `check_wholesaler_availability` lub automatycznie w `request_quotes_and_evaluate`). Jeśli towar jest niedostępny w danej ilości, zapytania o cenę nie są wysyłane.
   - Gdy produkt jest dostępny, zbierasz oferty cenowe (PROPOSAL) wyłącznie z hurtowni posiadających towar, porównujesz je regułą min(total_cost), sprawdzasz dostępny budżet w portfelu SQL i opcjonalnie przesyłasz zamówienie (`request_quotes_and_evaluate`).
   - Alternatywnie możesz utworzyć zapytanie ofertowe CALL_FOR_PROPOSAL (narzędzie `create_procurement_request` lub `check_and_trigger_procurement`).
   - Posiadaną listę ofert PROPOSAL oceniasz narzędziem `evaluate_proposals`.
   - Wybór hurtowni jest deterministyczny: wybierasz ofertę o najniższym koszcie całkowitym min(total_cost), biorąc pod uwagę budżet.
   - Generujesz komunikat ACCEPT_PROPOSAL dla zwycięzcy oraz REJECT_PROPOSAL dla pozostałych hurtowni.
   - Po dostarczeniu towaru rejestrujesz go w magazynie narzędziem `receive_delivery`, co powoduje automatyczne rozliczenie płatności w bazie SQL.
5. Zgodność ze schematami:
   - Wszystkie tworzone komunikaty i dane muszą w 100% odpowiadać schematom z katalogu docs/schemas/ (availability-request.json, availability-response.json, request-offer.json, response-offer.json, accept-offer.json, reject.json, item.json).

Zawsze korzystaj z dostępnych narzędzi, aby badać stan faktyczny magazynu oraz portfela i podejmować realne akcje. Odpowiadaj rzeczowo i precyzyjnie w języku polskim."""


class RestaurantBrain:
    """
    LLM Brain for Restaurant 1 powered by Groq API.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        agent_backend: Optional[RestaurantAgent] = None,
    ):
        self.api_key = api_key or config.GROQ_API_KEY
        self.model = model or config.GROQ_MODEL
        self.agent_backend = agent_backend or default_agent
        self.client: Optional[Groq] = None

        if self.api_key and self.api_key != "twoj_klucz_groq":
            try:
                self.client = Groq(api_key=self.api_key)
                logger.info(f"[{config.AGENT_ID}] Initialized Groq client with model '{self.model}'")
            except Exception as e:
                logger.error(f"[{config.AGENT_ID}] Failed to initialize Groq client: {e}")
                self.client = None
        else:
            logger.warning(
                f"[{config.AGENT_ID}] No valid GROQ_API_KEY configured. "
                "Set GROQ_API_KEY in .env or environment to enable real LLM inference."
            )

    def run_conversation(
        self, messages: List[Dict[str, Any]], max_iterations: int = 8
    ) -> List[Dict[str, Any]]:
        """
        Executes a multi-turn tool-calling conversation loop with Groq API.
        """
        if not self.client:
            raise RuntimeError(
                "Groq client is not configured. Please supply a valid GROQ_API_KEY in .env or constructor."
            )

        current_messages = list(messages)

        for step in range(max_iterations):
            logger.debug(f"[Groq:Loop] Iteration {step + 1}/{max_iterations}")

            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=current_messages,
                    tools=GROQ_TOOLS,
                    tool_choice="auto",
                )
            except Exception as e:
                logger.error(f"[Groq:Error] Chat completion failed: {e}")
                raise

            choice = response.choices[0]
            msg = choice.message
            tool_calls = getattr(msg, "tool_calls", None)

            # If no tool calls, append final assistant reply and stop
            if not tool_calls:
                current_messages.append({"role": "assistant", "content": msg.content or ""})
                logger.debug("[Groq:Loop] Assistant finished without tool calls.")
                break

            # Append assistant message with tool calls to conversation history
            assistant_turn = {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ],
            }
            current_messages.append(assistant_turn)

            # Execute each tool call and append corresponding tool role message
            for tc in tool_calls:
                func_name = tc.function.name
                func_args = tc.function.arguments
                logger.info(f"[Groq:ToolCall] Executing: {func_name}({func_args})")

                tool_result_str = execute_tool(
                    name=func_name,
                    arguments=func_args,
                    agent=self.agent_backend,
                )

                tool_message = {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": func_name,
                    "content": tool_result_str,
                }
                current_messages.append(tool_message)

        return current_messages

    def ask(self, user_prompt: str) -> str:
        """
        Submits a user prompt, executes any necessary tools, and returns the final assistant answer.
        """
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        history = self.run_conversation(messages)
        last_msg = history[-1]
        return last_msg.get("content", "")

    def run_autonomous_audit(self) -> str:
        """
        Runs an autonomous audit prompt commanding the agent to inspect stock, detect shortages,
        and initiate procurement if required.
        """
        prompt = (
            "Przeprowadź audyt stanu spiżarni Restauracji nr 1. "
            "Sprawdź czy jakiekolwiek składniki są poniżej progu bezpieczeństwa. "
            "Jeśli tak, zgłoś zapotrzebowanie ofertowe CALL_FOR_PROPOSAL do hurtowni H1 i H2."
        )
        return self.ask(prompt)


def main():
    parser = argparse.ArgumentParser(description="Restaurant 1 Groq Agent Brain")
    parser.add_argument("--prompt", type=str, help="Prompt to send to the agent")
    parser.add_argument("--audit", action="store_true", help="Run autonomous inventory audit")
    parser.add_argument("--model", type=str, default=config.GROQ_MODEL, help="Groq model override")
    args = parser.parse_args()

    brain = RestaurantBrain(model=args.model)

    if not config.is_groq_configured():
        print("\n[OSTRZEŻENIE] GROQ_API_KEY nie jest skonfigurowany lub posiada wartość domyślną.")
        print("Ustaw swój klucz w pliku restaurant-1/.env (na bazie .env.example).\n")
        return

    if args.audit:
        print(f"[R1 Agent] Uruchamianie autonomicznego audytu z modelem '{brain.model}'...")
        answer = brain.run_autonomous_audit()
        print("\nOdpowiedź Agenta:")
        print(answer)
    elif args.prompt:
        print(f"[R1 Agent] Pytanie: {args.prompt}")
        answer = brain.ask(args.prompt)
        print("\nOdpowiedź Agenta:")
        print(answer)
    else:
        print(f"[R1 Agent] Tryb interaktywny z modelem '{brain.model}'. Wpisz 'exit' aby zakończyć.\n")
        while True:
            try:
                user_input = input("Ty > ")
                if user_input.strip().lower() in ("exit", "quit", "q"):
                    break
                if not user_input.strip():
                    continue
                resp = brain.ask(user_input)
                print(f"\nR1 > {resp}\n")
            except (KeyboardInterrupt, EOFError):
                break


if __name__ == "__main__":
    main()
