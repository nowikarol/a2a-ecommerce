"""
Agent package for Restaurant 1.
Contains the LLM agent brain (Google AI Studio / Gemini), business logic tools, and tool execution dispatcher.
"""

from agent.tools import RestaurantAgent, default_agent, GEMINI_TOOLS, execute_tool
from agent.agent import RestaurantBrain, SYSTEM_PROMPT

__all__ = [
    "RestaurantAgent",
    "default_agent",
    "GEMINI_TOOLS",
    "execute_tool",
    "RestaurantBrain",
    "SYSTEM_PROMPT",
]

