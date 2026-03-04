"""Parse LLM responses into GameAction dataclasses."""

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class GameAction:
    """Represents a single game action to execute."""
    action_type: str  # key_press, key_hold, mouse_click, mouse_move, wait, none
    args: list[str]

    def __str__(self):
        return f"{self.action_type} {' '.join(self.args)}"


@dataclass
class LLMResponse:
    """Parsed LLM response with thought and actions."""
    thought: str
    actions: list[GameAction]
    raw: str

    @property
    def action(self) -> GameAction:
        """Backward compatible: return the first action."""
        return self.actions[0] if self.actions else GameAction(action_type="none", args=[])


def parse_response(text: str) -> LLMResponse:
    """Parse THOUGHT:/ACTION: format from LLM response.

    Supports multiple ACTION lines:
        THOUGHT: some reasoning here
        ACTION: key_press tab
        ACTION: key_hold w 2.0

    If parsing fails, returns a single 'wait' action.
    """
    raw = text.strip()
    # Strip <think>...</think> blocks from thinking models (e.g. qwen3.5)
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    thought = ""

    # Extract THOUGHT
    thought_match = re.search(r"THOUGHT:\s*(.+?)(?=\nACTION:|\Z)", raw, re.DOTALL)
    if thought_match:
        thought = thought_match.group(1).strip()

    # Extract all ACTION lines
    action_strings = re.findall(r"ACTION:\s*(.+?)(?:\n|$)", raw)

    # Fallback: if no THOUGHT/ACTION found, scan free-form text for action patterns
    if not action_strings and not thought:
        thought = raw[:200] if raw else ""
        # Look for action-like patterns in free-form text
        # _ARG matches: multi-char key names, single letter keys (only if followed by space/punct/end), or numbers
        _NAMED_KEYS = (r"space|enter|return|escape|esc|tab|shift|lshift|rshift"
                       r"|ctrl|lctrl|rctrl|alt|lalt|ralt|backspace|delete"
                       r"|up|down|left|right|f[1-9]|f1[0-2]")
        _NUM = r"\d+(?:\.\d+)?"
        # Single letter key: must NOT be followed by more letters (word boundary)
        _ARG = rf"(?:{_NAMED_KEYS}|[a-z](?![a-z])|{_NUM})"
        action_names = "|".join(VALID_ACTIONS - {"none", "wait"})
        action_pattern = rf"\b({action_names})\s+({_ARG}(?:\s+{_ARG}){{0,3}})"
        found = re.findall(action_pattern, raw, re.IGNORECASE)
        if found:
            action_strings = [f"{act} {args.strip()}" for act, args in found]
            logger.info("Extracted actions from free-form text: %s", action_strings)

    actions = [_parse_action(s.strip()) for s in action_strings] if action_strings else [_parse_action("")]

    return LLMResponse(thought=thought, actions=actions, raw=raw)


VALID_ACTIONS = {"key_press", "key_hold", "mouse_click", "mouse_hold", "mouse_move", "zoom_in", "zoom_out", "wait", "none", "ask_wiki"}


def _parse_action(action_str: str) -> GameAction:
    """Parse an action string like 'key_press e' into a GameAction."""
    if not action_str:
        return GameAction(action_type="none", args=[])

    parts = action_str.split()
    action_type = parts[0].lower()
    args = parts[1:]

    if action_type not in VALID_ACTIONS:
        logger.warning("Unknown action type '%s', defaulting to wait", action_type)
        return GameAction(action_type="wait", args=["1"])

    # Validate argument counts
    if action_type == "key_press" and len(args) < 1:
        logger.warning("key_press requires a key argument")
        return GameAction(action_type="none", args=[])
    if action_type == "key_hold" and len(args) < 2:
        logger.warning("key_hold requires key and duration arguments")
        return GameAction(action_type="none", args=[])
    if action_type == "mouse_click" and len(args) < 2:
        logger.warning("mouse_click requires x and y arguments")
        return GameAction(action_type="none", args=[])
    if action_type == "mouse_hold" and len(args) < 2:
        logger.warning("mouse_hold requires x and y arguments")
        return GameAction(action_type="none", args=[])
    if action_type == "mouse_move" and len(args) < 2:
        logger.warning("mouse_move requires x and y arguments")
        return GameAction(action_type="none", args=[])

    return GameAction(action_type=action_type, args=args)


if __name__ == "__main__":
    test = "THOUGHT: I see a stone furnace. Let me interact.\nACTION: key_press e"
    result = parse_response(test)
    print(f"Thought: {result.thought}")
    print(f"Action (compat): {result.action}")
    print(f"Actions: {result.actions}")

    test2 = "THOUGHT: 지도가 열려있다. 닫고 이동해야 한다.\nACTION: key_press tab\nACTION: key_hold w 2.0"
    result2 = parse_response(test2)
    print(f"\nMulti-action test:")
    print(f"Thought: {result2.thought}")
    for i, a in enumerate(result2.actions):
        print(f"  Action {i+1}: {a}")
