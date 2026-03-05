"""FastMCP server for Factorio Game Bot.

Initializes shared state (ScreenCapture, GameInput, OllamaClient) and
exposes game interaction tools over the MCP stdio transport.
"""

import os
import sys

# Ensure project root is on sys.path so body/memory imports work.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from mcp.server.fastmcp import FastMCP

from body.screen_capture import ScreenCapture
from body.game_input import GameInput
from body.ollama_client import OllamaClient
from memory.database import init_db
from memory.knowledge import KnowledgeStore

# --------------- shared state ---------------

capture = ScreenCapture()
if not capture.find_window():
    print("WARNING: Factorio window not found. Tools will fail until the game is running.",
          file=sys.stderr)

game_input = GameInput(
    window_offset=capture.window_offset,
    hwnd=capture._hwnd,
)

use_vision = os.environ.get("FACTORIO_USE_VISION", "false").lower() == "true"
vision_model = os.environ.get("FACTORIO_VISION_MODEL", "qwen3-vl:4b")
ollama = OllamaClient() if use_vision else None

init_db()
knowledge = KnowledgeStore()

# --------------- FastMCP app ---------------

mcp = FastMCP("factorio")

# Register tools from tools module (they reference the shared state above)
from mcp_server.tools import register_tools  # noqa: E402
register_tools(mcp, capture, game_input, ollama, knowledge, use_vision, vision_model)

if __name__ == "__main__":
    mcp.run(transport="stdio")
