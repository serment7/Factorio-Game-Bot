"""MCP tool definitions for Factorio Game Bot.

All action tools follow the same pattern:
  execute action -> wait for screen to stabilize -> capture -> (optional) vision analysis -> return [text, Image]
"""

import io
import time
import logging

from mcp.server.fastmcp import FastMCP, Image

from body.screen_capture import ScreenCapture
from body.game_input import GameInput
from body.ollama_client import OllamaClient
from memory.knowledge import KnowledgeStore

logger = logging.getLogger(__name__)

STABILIZE_DELAY = 0.3  # seconds to wait for screen to stabilize after action


def _capture_and_describe(
    capture: ScreenCapture,
    ollama: OllamaClient | None,
    use_vision: bool,
    vision_model: str,
    action_description: str = "",
) -> list:
    """Capture screenshot, optionally run vision analysis, return [text, Image]."""
    # Refresh window geometry in case it moved
    capture._refresh_rect()

    b64, img_hash, pil_img = capture.capture_base64()

    # Convert to JPEG bytes for MCP Image
    buf = io.BytesIO()
    pil_img.save(buf, format="JPEG", quality=80)
    jpeg_bytes = buf.getvalue()

    size = capture.window_size
    text_parts = []
    if action_description:
        text_parts.append(f"Action: {action_description}")
    text_parts.append(f"Screen size: {size[0]}x{size[1]}" if size else "Screen size: unknown")
    text_parts.append(f"Screenshot hash: {img_hash}")

    # Optional vision model analysis
    if use_vision and ollama:
        try:
            vision_text = ollama.chat(
                system_prompt="You are analyzing a Factorio game screenshot. Describe what you see concisely: player position, nearby resources, buildings, UI elements, and any notable details.",
                user_text="Describe this Factorio game screenshot.",
                image_b64=b64,
                model=vision_model,
            )
            text_parts.append(f"Vision analysis: {vision_text}")
        except Exception as e:
            text_parts.append(f"Vision analysis failed: {e}")

    return ["\n".join(text_parts), Image(data=jpeg_bytes, format="jpeg")]


def register_tools(
    mcp: FastMCP,
    capture: ScreenCapture,
    game_input: GameInput,
    ollama: OllamaClient | None,
    knowledge: KnowledgeStore,
    use_vision: bool,
    vision_model: str,
):
    """Register all 10 MCP tools on the given FastMCP app."""

    def _cap(action_desc: str = "") -> list:
        return _capture_and_describe(capture, ollama, use_vision, vision_model, action_desc)

    @mcp.tool()
    def look() -> list:
        """Capture the current Factorio game screen without performing any action. Use this to observe the current state."""
        return _cap("look (observe only)")

    @mcp.tool()
    def key_press(key: str) -> list:
        """Press a key once. Use for UI interactions like opening inventory (e), map (tab), escape, etc.

        Args:
            key: Key name (e.g. 'e', 'tab', 'escape', 'space', 'enter', 'f1'-'f12', '1'-'9')
        """
        game_input._focus_game()
        game_input.key_press(key)
        time.sleep(STABILIZE_DELAY)
        return _cap(f"key_press({key})")

    @mcp.tool()
    def key_hold(key: str, duration: float = 1.0) -> list:
        """Hold a key for a duration. Use for WASD movement.

        Args:
            key: Key name (e.g. 'w', 'a', 's', 'd' for movement)
            duration: How long to hold in seconds (default 1.0)
        """
        game_input._focus_game()
        game_input.key_hold(key, duration)
        time.sleep(STABILIZE_DELAY)
        return _cap(f"key_hold({key}, {duration}s)")

    @mcp.tool()
    def mouse_click(x: int, y: int, button: str = "left") -> list:
        """Click the mouse at image coordinates.

        Args:
            x: X coordinate in the game screenshot (0 = left edge)
            y: Y coordinate in the game screenshot (0 = top edge)
            button: 'left' or 'right' (default 'left')
        """
        game_input._focus_game()
        game_input.mouse_click(x, y, button)
        time.sleep(STABILIZE_DELAY)
        return _cap(f"mouse_click({x}, {y}, {button})")

    @mcp.tool()
    def mouse_hold(x: int, y: int, duration: float = 2.0, button: str = "right") -> list:
        """Hold mouse button at image coordinates. Use right-click hold for mining resources.

        Args:
            x: X coordinate in the game screenshot
            y: Y coordinate in the game screenshot
            duration: How long to hold in seconds (default 2.0)
            button: 'left' or 'right' (default 'right')
        """
        game_input._focus_game()
        game_input.mouse_hold(x, y, duration, button)
        time.sleep(STABILIZE_DELAY)
        return _cap(f"mouse_hold({x}, {y}, {duration}s, {button})")

    @mcp.tool()
    def mouse_move(x: int, y: int) -> list:
        """Move mouse cursor to image coordinates without clicking.

        Args:
            x: X coordinate in the game screenshot
            y: Y coordinate in the game screenshot
        """
        game_input._focus_game()
        game_input.mouse_move(x, y)
        time.sleep(0.1)
        return _cap(f"mouse_move({x}, {y})")

    @mcp.tool()
    def zoom_in(steps: int = 3) -> list:
        """Zoom in the game view by scrolling the mouse wheel up.

        Args:
            steps: Number of scroll steps (default 3)
        """
        game_input._focus_game()
        game_input.mouse_scroll(steps)
        time.sleep(STABILIZE_DELAY)
        return _cap(f"zoom_in({steps})")

    @mcp.tool()
    def zoom_out(steps: int = 3) -> list:
        """Zoom out the game view by scrolling the mouse wheel down.

        Args:
            steps: Number of scroll steps (default 3)
        """
        game_input._focus_game()
        game_input.mouse_scroll(-steps)
        time.sleep(STABILIZE_DELAY)
        return _cap(f"zoom_out({steps})")

    @mcp.tool()
    def wait(seconds: float = 1.0) -> list:
        """Wait for a specified duration then capture the screen. Use to let animations or actions complete.

        Args:
            seconds: Duration to wait (default 1.0)
        """
        time.sleep(seconds)
        return _cap(f"wait({seconds}s)")

    @mcp.tool()
    def perform_actions(actions: list[str]) -> list:
        """Execute multiple actions in sequence, then capture once at the end. Much faster than calling tools one by one.

        Each action is a string in the format: "action_type arg1 arg2 ..."

        Supported actions:
          - key_press <key>                    (e.g. "key_press e")
          - key_hold <key> <duration>          (e.g. "key_hold d 2.0")
          - mouse_click <x> <y> [button]       (e.g. "mouse_click 400 300 left")
          - mouse_hold <x> <y> <duration> [button] (e.g. "mouse_hold 400 300 3.0 right")
          - mouse_move <x> <y>                 (e.g. "mouse_move 400 300")
          - zoom_in [steps]                    (e.g. "zoom_in 3")
          - zoom_out [steps]                   (e.g. "zoom_out 3")
          - wait <seconds>                     (e.g. "wait 1.0")

        Example: ["key_press e", "wait 0.5", "mouse_click 400 300 left", "key_press escape"]

        Args:
            actions: List of action strings to execute in order
        """
        game_input._focus_game()
        executed = []
        for action_str in actions:
            parts = action_str.strip().split()
            if not parts:
                continue
            action_type = parts[0]
            args = parts[1:]
            success = game_input.execute(action_type, args)
            executed.append(f"{action_str} -> {'ok' if success else 'FAILED'}")
            time.sleep(0.15)
        time.sleep(STABILIZE_DELAY)
        desc = f"perform_actions({len(executed)} actions):\n" + "\n".join(f"  {e}" for e in executed)
        return _cap(desc)

    @mcp.tool()
    def query_knowledge(topic: str) -> str:
        """Query the knowledge database for Factorio game information.

        Args:
            topic: Topic to search for (e.g. 'iron', 'crafting', 'controls')
        """
        results = knowledge.search_wiki(topic)
        if results:
            parts = []
            for r in results[:5]:
                parts.append(f"## {r['topic']}\n{r['content']}")
            return "\n\n".join(parts)

        # Also check known controls
        controls = knowledge.get_controls(min_confidence=0.3)
        matching = [c for c in controls if topic.lower() in c["key"].lower() or topic.lower() in c["effect"].lower()]
        if matching:
            parts = ["## Matching Controls"]
            for c in matching[:10]:
                parts.append(f"- {c['key']}: {c['effect']} (confidence: {c['confidence']:.1f})")
            return "\n".join(parts)

        return f"No knowledge found for topic: {topic}"
