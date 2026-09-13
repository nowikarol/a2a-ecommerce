"""
Configuration module for Restaurant 1 (restaurant-1).
Loads environment variables and sets up Groq API settings and paths.
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

# Groq API Configuration
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
# Default model: openai/gpt-oss-120b (fast and highly capable tool calling)
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
# Fallback model options: qwen/qwen3.6-27b
FALLBACK_MODEL: str = "openai/gpt-oss-120b"

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

# Financial Wallet Configuration
DEFAULT_CURRENCY: str = os.getenv("RESTAURANT_CURRENCY", "PLN")
INITIAL_BALANCE: float = float(os.getenv("RESTAURANT_INITIAL_BALANCE", "5000.0"))

# Wholesaler Endpoints (MCP Servers for H1, H2)
WHOLESALER_ENDPOINTS: dict[str, str] = {
    "H1": os.getenv("H1_MCP_URL", "http://127.0.0.1:8001/sse"),
    "H2": os.getenv("H2_MCP_URL", "http://127.0.0.1:8002/sse"),
}
MCP_CLIENT_TIMEOUT: float = float(os.getenv("MCP_CLIENT_TIMEOUT", "3.0"))


def is_groq_configured() -> bool:
    """Checks if a non-placeholder GROQ_API_KEY is available."""
    return bool(GROQ_API_KEY and GROQ_API_KEY != "twoj_klucz_groq")
