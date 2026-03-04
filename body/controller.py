"""Main Body loop: capture → LLM inference → action execution → learning."""

import json
import logging
import threading
import time
from pathlib import Path

from body.screen_capture import ScreenCapture
from body.ollama_client import OllamaClient
from body.action_parser import parse_response
from body.game_input import GameInput
from memory.knowledge import KnowledgeStore

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class BodyController:
    """Runs the Body loop: capture → infer → act → learn."""

    def __init__(self, knowledge: KnowledgeStore, goal_getter=None,
                 log_callback=None, wiki_requester=None):
        self.knowledge = knowledge
        self.goal_getter = goal_getter or (lambda: "Explore the game and learn controls.")
        self.log_callback = log_callback or (lambda msg: None)
        self.wiki_requester = wiki_requester  # callable(topic) -> None

        self.capture = ScreenCapture()
        self.llm = OllamaClient()
        self.game_input = GameInput()
        self._action_thread: threading.Thread | None = None
        self._waiting_wiki = False
        self._last_wiki_count = 0
        self._wiki_wait_start = 0.0

        self._running = False
        self._thread: threading.Thread | None = None
        self._system_prompt = self._load_system_prompt()
        self.cycle_count = 0
        self.last_cycle_time = 0.0
        self.last_capture = None  # PIL Image of latest capture

    def _load_system_prompt(self) -> str:
        path = PROMPTS_DIR / "body_system.txt"
        if path.exists():
            return path.read_text(encoding="utf-8")
        logger.warning("Body system prompt not found at %s", path)
        return "You control a game. Respond with THOUGHT: and ACTION: lines."

    def _build_prompt_context(self) -> str:
        """Fill in the system prompt template with current knowledge."""
        prompt = self._system_prompt

        # Dynamic screen size
        size = self.capture.window_size
        if size:
            prompt = prompt.replace("{screen_width}", str(size[0]))
            prompt = prompt.replace("{screen_height}", str(size[1]))
        else:
            prompt = prompt.replace("{screen_width}", "?")
            prompt = prompt.replace("{screen_height}", "?")

        # Known controls
        controls = self.knowledge.get_controls(min_confidence=0.3)
        if controls:
            ctrl_lines = [f"- {c['key']}: {c['effect']} (confidence: {c['confidence']:.1f})"
                          for c in controls[:15]]
            prompt = prompt.replace("{known_controls}", "\n".join(ctrl_lines))
        else:
            prompt = prompt.replace("{known_controls}", "아직 없음.")

        # Current goal
        prompt = prompt.replace("{current_goal}", self.goal_getter())

        # Recent actions
        recent = self.knowledge.get_recent_observations(limit=20)
        if recent:
            action_lines = [f"- {o['action_type']} {o['action_args']}: {o['thought'][:80]}"
                            for o in recent]
            prompt = prompt.replace("{recent_actions}", "\n".join(action_lines))
        else:
            prompt = prompt.replace("{recent_actions}", "없음.")

        # Wiki knowledge (Brain이 알려준 정보)
        wikis = self.knowledge.search_wiki("")
        if wikis:
            wiki_lines = [f"- {w['topic']}: {w['content'][:200]}" for w in wikis[:5]]
            prompt += "\n\n## Brain이 알려준 정보\n" + "\n".join(wiki_lines)

        return prompt

    def _cycle(self) -> None:
        """Execute one body cycle."""
        start = time.time()

        # Wiki 응답 대기 중이면 대기 (최대 30초)
        if self._waiting_wiki:
            current_wiki_count = self.knowledge.get_stats().get("wiki_entries", 0)
            if current_wiki_count > self._last_wiki_count:
                self._waiting_wiki = False
                self.log_callback("[Body] Wiki 응답 도착 — 재개")
            elif time.time() - self._wiki_wait_start > 30:
                self._waiting_wiki = False
                self.log_callback("[Body] Wiki 응답 타임아웃 (30초) — 재개")
            else:
                self.log_callback("[Body] Brain wiki 응답 대기 중...")
                time.sleep(2)
                self.last_cycle_time = time.time() - start
                return

        # Sync window handle and offset for mouse coordinate mapping
        self.game_input.hwnd = self.capture._hwnd
        self.game_input.window_offset = self.capture.window_offset

        # 1. Capture
        t_capture = time.time()
        try:
            image_b64, img_hash, pil_img = self.capture.capture_base64()
            self.last_capture = pil_img
        except Exception as e:
            logger.error("Screen capture failed: %s", e)
            self.log_callback(f"[Body] Capture error: {e}")
            return
        capture_ms = (time.time() - t_capture) * 1000

        # 2. LLM Inference
        t_infer = time.time()
        system_prompt = self._build_prompt_context()
        user_msg = "이 팩토리오 게임 스크린샷을 분석하고 다음 행동을 결정해라."

        response_text = self.llm.chat(system_prompt, user_msg, image_b64)
        parsed = parse_response(response_text)
        infer_ms = (time.time() - t_infer) * 1000

        self.log_callback(f"[Body] ⏱ 캡처 {capture_ms:.0f}ms → 추론 {infer_ms:.0f}ms (합계 {capture_ms+infer_ms:.0f}ms)")
        if not parsed.thought and parsed.action.action_type == "none":
            self.log_callback(f"[Body] RAW ({len(response_text)} chars): {repr(response_text[:300])}")
        self.log_callback(f"[Body] THOUGHT: {parsed.thought}")
        for i, act in enumerate(parsed.actions):
            self.log_callback(f"[Body] ACTION[{i+1}/{len(parsed.actions)}]: {act}")

        # 3. Handle actions — check for ask_wiki first
        has_wiki = any(a.action_type == "ask_wiki" for a in parsed.actions)
        if has_wiki:
            wiki_action = next(a for a in parsed.actions if a.action_type == "ask_wiki")
            topic = " ".join(wiki_action.args) if wiki_action.args else "팩토리오 기본 조작법"
            if self.wiki_requester:
                self.wiki_requester(topic)
                self.log_callback(f"[Body] Brain에게 질문: {topic}")
                self._waiting_wiki = True
                self._wiki_wait_start = time.time()
                self._last_wiki_count = self.knowledge.get_stats().get("wiki_entries", 0)
        else:
            # 게임 행동 → 스레드에서 순차 실행 + 완료 대기
            game_actions = [a for a in parsed.actions
                           if a.action_type not in ("none", "wait")]
            if game_actions:
                def _run_actions():
                    for act in game_actions:
                        self.game_input.execute(act.action_type, act.args)
                        time.sleep(0.15)  # 액션 간 간격
                self._action_thread = threading.Thread(target=_run_actions, daemon=True)
                self._action_thread.start()
                self._action_thread.join(timeout=15)  # 완료 대기

            # 4. Feature E — 후 캡처: 화면 변화가 안정될 때까지 폴링
            after_b64, after_hash = None, img_hash
            try:
                prev_hash = img_hash
                for _ in range(10):  # 최대 ~1초 (100ms × 10)
                    time.sleep(0.1)
                    after_b64, after_hash, _ = self.capture.capture_base64()
                    if after_hash != img_hash:
                        # 변화 감지 — 한 번 더 확인해서 안정됐는지 체크
                        time.sleep(0.15)
                        after_b64, after_hash, _ = self.capture.capture_base64()
                        break
            except Exception:
                after_b64, after_hash = None, img_hash

            changed = after_hash != img_hash
            success = 1 if changed else 0
            if changed:
                self.log_callback("[Body] 결과: 화면변화 있음 ✓")
            else:
                self.log_callback("[Body] 결과: 변화 없음 ✗")

        # 5. Build action summary string
        action_summary = " → ".join(str(a) for a in parsed.actions)

        # 6. Save observation
        if has_wiki:
            self.knowledge.add_observation(
                screenshot_hash=img_hash,
                thought=parsed.thought,
                action_type=parsed.action.action_type,
                action_args=action_summary,
            )
        else:
            self.knowledge.add_observation(
                screenshot_hash=img_hash,
                thought=parsed.thought,
                action_type=parsed.action.action_type,
                action_args=action_summary,
                result_hash=after_hash,
                success=success,
            )

            # 7. Feature A — 지식 추출 (화면 변화 시)
            if changed and after_b64:
                self._extract_knowledge(action_summary, after_b64)

        self.cycle_count += 1
        self.last_cycle_time = time.time() - start

    def _extract_knowledge(self, action_str: str, after_b64: str) -> None:
        """Feature A: extract controls/entities/recipes from a successful action."""
        try:
            prompt = (
                f'방금 "{action_str}"을 실행했고 화면이 변했다.\n'
                f'이 스크린샷에서 **실제로 눈에 보이는 것만** 기반으로 답해라.\n'
                f'추측하거나 일반 지식으로 답하지 마라. 화면에 없으면 빈 리스트로 답해라.\n'
                f'JSON 형식:\n'
                f'{{"controls":[{{"key":"키","effect":"효과"}}],'
                f'"entities":[{{"name":"이름","category":"분류"}}],'
                f'"recipes":[{{"output":"결과물","input":"재료"}}]}}\n'
                f'JSON만 답해라.'
            )
            response = self.llm.chat(
                "스크린샷에 실제로 보이는 것만 추출해라. 추측 금지. JSON만 답해라.",
                prompt, after_b64
            )

            # Extract JSON from response (handle markdown fences)
            text = response.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            data = json.loads(text)

            count = 0
            for ctrl in data.get("controls", []):
                if ctrl.get("key") and ctrl.get("effect"):
                    self.knowledge.add_control(
                        key=ctrl["key"], context="game", effect=ctrl["effect"]
                    )
                    count += 1
                    self.log_callback(f"[Body] 학습: control {ctrl['key']}={ctrl['effect']}")

            for ent in data.get("entities", []):
                if ent.get("name"):
                    self.knowledge.add_entity(
                        name=ent["name"], category=ent.get("category", "")
                    )
                    count += 1
                    self.log_callback(f"[Body] 학습: entity {ent['name']}")

            for rec in data.get("recipes", []):
                if rec.get("output") and rec.get("input"):
                    self.knowledge.add_recipe(
                        output_item=rec["output"], input_items=rec["input"]
                    )
                    count += 1
                    self.log_callback(f"[Body] 학습: recipe {rec['output']}")

            if count > 0:
                self.log_callback(f"[Body] 지식 추출: {count}개 항목 학습")
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.debug("Knowledge extraction parse error (ignored): %s", e)
        except Exception as e:
            logger.warning("Knowledge extraction failed: %s", e)

    def _loop(self) -> None:
        logger.info("Body loop started.")
        self.log_callback("[Body] 루프 시작.")
        while self._running:
            try:
                self._cycle()
            except Exception as e:
                logger.error("Body cycle error: %s", e)
                self.log_callback(f"[Body] Error: {e}")
        logger.info("Body loop stopped.")
        self.log_callback("[Body] 루프 정지.")

    def start(self) -> None:
        if self._running:
            return
        if not self.llm.is_available():
            self.log_callback("[Body] ERROR: Ollama에 연결할 수 없습니다!")
            logger.error("Cannot start Body: Ollama unavailable")
            return
        if not self.capture.find_window():
            self.log_callback("[Body] ERROR: 팩토리오 윈도우를 찾을 수 없습니다!")
            logger.error("Cannot start Body: Factorio window not found")
            return
        self.game_input.hwnd = self.capture._hwnd
        self.game_input.window_offset = self.capture.window_offset
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="BodyThread")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    @property
    def is_running(self) -> bool:
        return self._running
