"""
Configuration module for Restaurant 1 (restaurant-1).
Loads environment variables and sets up Gemini (Google AI Studio) API settings and paths.
"""

import os
from pathlib import Path
import sys
from dotenv import load_dotenv

# Base paths
CURRENT_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = CURRENT_DIR.parent
ENV_PATH = CURRENT_DIR / ".env"
WORKSPACE_ENV_PATH = WORKSPACE_DIR / ".env"

# Load .env file (first try restaurant-1/.env, then workspace/.env)
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
elif WORKSPACE_ENV_PATH.exists():
    load_dotenv(dotenv_path=WORKSPACE_ENV_PATH)
else:
    load_dotenv()

# Gemini (Google AI Studio) API Configuration
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
GEMINI_BASE_URL: str = os.getenv(
    "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"
)
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
FALLBACK_MODEL: str = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.6-flash")

# Agent Identity & Node Configuration
AGENT_ID: str = "R1"
AGENT_NAME: str = "Restauracja nr 1"

# Ensure restaurant-1 root is on sys.path
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

# Paths to data stores
DATA_DIR: Path = CURRENT_DIR / "data"
DB_PATH: Path = DATA_DIR / "restaurant.db"
INVENTORY_PATH: Path = DATA_DIR / "inventory.json"
RECIPES_PATH: Path = DATA_DIR / "recipes.json"
SCHEMAS_DIR: Path = WORKSPACE_DIR / "docs" / "schemas"

# Server Configuration (R1: 8002)
PORT: int = int(os.getenv("R1_PORT", os.getenv("PORT", "8002")))
SERVER_PORT: int = PORT

# Financial Wallet Configuration
DEFAULT_CURRENCY: str = os.getenv("RESTAURANT_CURRENCY", "PLN")
INITIAL_BALANCE: float = float(os.getenv("RESTAURANT_INITIAL_BALANCE", "5000.0"))

# Wholesaler Endpoints (MCP Servers for H1, H2)
WHOLESALER_ENDPOINTS: dict[str, str] = {
    "H1": os.getenv("H1_MCP_URL", "http://127.0.0.1:8004/sse"),
    "H2": os.getenv("H2_MCP_URL", "http://127.0.0.1:8005/sse"),
}
MCP_CLIENT_TIMEOUT: float = float(os.getenv("MCP_CLIENT_TIMEOUT", "3.0"))

# Auto-procurement / Reordering Configuration
AUTO_REORDER_ON_THRESHOLD: bool = os.getenv("AUTO_REORDER_ON_THRESHOLD", "true").lower() in ("true", "1", "yes")

# Conversational Memory Configuration (Window of recent messages, e.g. 3-4 messages)
MAX_MEMORY_MESSAGES: int = int(os.getenv("MAX_MEMORY_MESSAGES", "4"))


def is_gemini_configured() -> bool:
    """Checks if a non-placeholder GEMINI_API_KEY is available."""
    return bool(GEMINI_API_KEY and GEMINI_API_KEY != "twoj_klucz_gemini")

