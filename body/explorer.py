"""5-phase exploration engine for discovering game mechanics."""

import logging
import time
import string

import pyautogui

from body.screen_capture import ScreenCapture
from body.game_input import GameInput
from body.ollama_client import OllamaClient
from body.action_parser import parse_response
from memory.knowledge import KnowledgeStore

logger = logging.getLogger(__name__)

GRID_COLS = 4
GRID_ROWS = 4
KEY_TEST_DELAY = 0.5


class Explorer:
    """5-phase exploration engine for learning game mechanics.

    Phase 1: Key Discovery — press each key and observe changes
    Phase 2: Mouse Grid — click a grid to discover interactive areas
    Phase 3: UI Exploration — find menus, panels, and buttons
    Phase 4: Object Interaction — interact with discovered entities
    Phase 5: Guided Play — follow Brain goals with learned knowledge
    """

    def __init__(self, capture: ScreenCapture, game_input: GameInput,
                 llm: OllamaClient, knowledge: KnowledgeStore,
                 log_callback=None):
        self.capture = capture
        self.game_input = game_input
        self.llm = llm
        self.knowledge = knowledge
        self.log_callback = log_callback or (lambda msg: None)
        self.current_phase = 1
        self._stopped = False

    def stop(self):
        self._stopped = True

    def _win_size(self) -> tuple[int, int]:
        """Current game window client size."""
        return self.capture.window_size or (1024, 768)

    # --- Phase 1: Key Discovery ---

    KEYS_TO_TEST = (
        list(string.ascii_lowercase) +
        list(string.digits) +
        ["space", "tab", "escape", "enter", "shift", "ctrl",
         "f1", "f2", "f3", "f4", "f5"]
    )

    def phase1_key_discovery(self) -> None:
        """Press each key and ask LLM what changed."""
        self.log_callback("[Explorer] Phase 1: Key Discovery")
        self.current_phase = 1

        for key in self.KEYS_TO_TEST:
            if self._stopped:
                return

            before_b64, before_hash = self.capture.capture_base64()
            self.game_input.key_press(key)
            time.sleep(KEY_TEST_DELAY)
            after_b64, after_hash = self.capture.capture_base64()

            if before_hash == after_hash:
                continue

            prompt = (
                f"I pressed the '{key}' key in Factorio. "
                "Compare these two screenshots (before and after). "
                "What changed? Describe any visible difference briefly."
            )
            response = self.llm.chat(
                "You analyze Factorio game screenshots to identify UI changes.",
                prompt, after_b64,
            )

            if response and "no change" not in response.lower() and "nothing" not in response.lower():
                effect = response.strip()[:200]
                self.knowledge.add_control(key, "general", effect, confidence=0.4)
                self.log_callback(f"[Explorer] Key '{key}': {effect[:80]}")

            self.game_input.key_press("escape")
            time.sleep(0.3)

    # --- Phase 2: Mouse Grid Exploration ---

    def phase2_mouse_grid(self) -> None:
        """Click a grid of screen positions to discover interactive areas."""
        self.log_callback("[Explorer] Phase 2: Mouse Grid Exploration")
        self.current_phase = 2

        w, h = self._win_size()
        cell_w = w // GRID_COLS
        cell_h = h // GRID_ROWS

        for row in range(GRID_ROWS):
            for col in range(GRID_COLS):
                if self._stopped:
                    return

                x = col * cell_w + cell_w // 2
                y = row * cell_h + cell_h // 2

                _, before_hash = self.capture.capture_base64()
                self.game_input.mouse_click(x, y)
                time.sleep(0.5)
                after_b64, after_hash = self.capture.capture_base64()

                if before_hash != after_hash:
                    prompt = (
                        f"I clicked at position ({x}, {y}) in Factorio. "
                        "What do you see? Is there any interactive element here?"
                    )
                    response = self.llm.chat(
                        "You analyze Factorio game screenshots.",
                        prompt, after_b64,
                    )
                    if response:
                        self.log_callback(f"[Explorer] Click ({x},{y}): {response[:80]}")

                self.game_input.key_press("escape")
                time.sleep(0.2)

    # --- Phase 3: UI Exploration ---

    UI_HOTKEYS = ["e", "tab", "m", "t", "l", "p", "o"]

    def phase3_ui_exploration(self) -> None:
        """Open known UI panels and analyze their contents."""
        self.log_callback("[Explorer] Phase 3: UI Exploration")
        self.current_phase = 3

        for key in self.UI_HOTKEYS:
            if self._stopped:
                return

            self.game_input.key_press(key)
            time.sleep(0.5)

            img_b64, _ = self.capture.capture_base64()
            prompt = (
                f"I pressed '{key}' in Factorio to open a menu/panel. "
                "Describe what UI panel or menu is visible. "
                "List any buttons, tabs, items, or options you can see."
            )
            response = self.llm.chat(
                "You analyze Factorio game UI screenshots in detail.",
                prompt, img_b64,
            )
            if response:
                self.log_callback(f"[Explorer] UI '{key}': {response[:100]}")
                self.knowledge.add_wiki(
                    f"ui_panel_{key}", response[:500], source="explorer"
                )

            self.game_input.key_press("escape")
            time.sleep(0.3)

    # --- Phase 4: Object Interaction ---

    def phase4_object_interaction(self) -> None:
        """Look at the game world and try to interact with visible objects."""
        self.log_callback("[Explorer] Phase 4: Object Interaction")
        self.current_phase = 4

        img_b64, _ = self.capture.capture_base64()

        prompt = (
            "Look at this Factorio screenshot. "
            "List all game objects/entities you can see (resources, buildings, items, terrain features). "
            "For each, describe its approximate screen position (x, y) coordinates."
        )
        response = self.llm.chat(
            "You identify game objects in Factorio screenshots.",
            prompt, img_b64,
        )
        if not response:
            return

        self.log_callback(f"[Explorer] Visible objects: {response[:150]}")

        w, h = self._win_size()
        cx, cy = w // 2, h // 2

        interactions = [
            ("e", "interact/open"),
            ("left click hold", "mine"),
        ]
        for action_desc, purpose in interactions:
            if self._stopped:
                return

            _, before_hash = self.capture.capture_base64()

            if action_desc == "e":
                self.game_input.key_press("e")
            elif action_desc == "left click hold":
                sx, sy = self.game_input._screen_xy(cx, cy)
                pyautogui.mouseDown(sx, sy, button="left")
                time.sleep(2.0)
                pyautogui.mouseUp(button="left")

            time.sleep(0.5)
            after_b64, after_hash = self.capture.capture_base64()

            if before_hash != after_hash:
                prompt = f"I tried to {purpose} in Factorio. What happened? What changed?"
                resp = self.llm.chat(
                    "You analyze Factorio gameplay changes.",
                    prompt, after_b64,
                )
                if resp:
                    self.log_callback(f"[Explorer] {purpose}: {resp[:100]}")

            self.game_input.key_press("escape")
            time.sleep(0.3)

    # --- Phase 5: Guided Play ---

    def phase5_guided_play(self, goal: str, cycles: int = 10) -> None:
        """Follow a goal from Brain, using learned knowledge."""
        self.log_callback(f"[Explorer] Phase 5: Guided Play — {goal[:80]}")
        self.current_phase = 5

        for i in range(cycles):
            if self._stopped:
                return

            img_b64, img_hash = self.capture.capture_base64()

            controls = self.knowledge.get_controls(min_confidence=0.3)
            ctrl_str = "\n".join(
                f"- {c['key']}: {c['effect']}" for c in controls[:15]
            ) if controls else "None yet."

            recent = self.knowledge.get_recent_observations(limit=3)
            recent_str = "\n".join(
                f"- {o['action_type']} {o['action_args']}" for o in recent
            ) if recent else "None."

            prompt = (
                f"Goal: {goal}\n"
                f"Known controls:\n{ctrl_str}\n"
                f"Recent actions:\n{recent_str}\n"
                "What action should I take next? "
                "Respond with THOUGHT: and ACTION: format."
            )

            response = self.llm.chat(
                "You play Factorio to achieve goals. Respond with THOUGHT: and ACTION:",
                prompt, img_b64,
            )
            parsed = parse_response(response)
            self.log_callback(f"[Explorer] P5 [{i+1}/{cycles}]: {parsed.action}")

            self.game_input.execute(parsed.action.action_type, parsed.action.args)

            self.knowledge.add_observation(
                screenshot_hash=img_hash,
                thought=parsed.thought,
                action_type=parsed.action.action_type,
                action_args=" ".join(parsed.action.args),
            )
            time.sleep(0.5)

    # --- Run all phases ---

    def run_full_exploration(self, goal: str = "") -> None:
        self._stopped = False
        self.phase1_key_discovery()
        if self._stopped:
            return
        self.phase2_mouse_grid()
        if self._stopped:
            return
        self.phase3_ui_exploration()
        if self._stopped:
            return
        self.phase4_object_interaction()
        if self._stopped:
            return
        if goal:
            self.phase5_guided_play(goal)
