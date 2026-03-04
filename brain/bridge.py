"""BrainBridge: async communication between Body and Brain threads."""

import logging
import queue
import threading
import time

from brain.claude_client import ClaudeClient
from brain.prompts import build_goal_request, build_summary_request, build_wiki_request
from memory.knowledge import KnowledgeStore

logger = logging.getLogger(__name__)


class BrainBridge:
    """Manages Brain thread: periodic goal updates + wiki query queue."""

    def __init__(self, knowledge: KnowledgeStore, log_callback=None,
                 goal_interval: float = 60.0, summary_interval: float = 300.0):
        self.knowledge = knowledge
        self.log_callback = log_callback or (lambda msg: None)
        self.goal_interval = goal_interval
        self.summary_interval = summary_interval
        self.claude = ClaudeClient()

        self._current_goal = "Explore the game and discover basic controls."
        self._wiki_queue: queue.Queue[str] = queue.Queue()
        self._running = False
        self._thread: threading.Thread | None = None
        self.last_update_time = 0.0
        self._last_summary_time = 0.0
        self._summary_count = 0

    @property
    def current_goal(self) -> str:
        return self._current_goal

    def request_wiki(self, topic: str) -> None:
        self._wiki_queue.put(topic)

    def _update_goal(self) -> None:
        stats = self.knowledge.get_stats()
        recent = self.knowledge.get_recent_observations(limit=10)
        controls = self.knowledge.get_controls(min_confidence=0.3)
        entities = self.knowledge.get_entities()

        goal = self.knowledge.get_active_goal()
        current = goal["goal_text"] if goal else self._current_goal

        prompt = build_goal_request(current, stats, recent, controls, entities)
        self.log_callback("[Brain] Asking Claude for next goal...")

        response = self.claude.query(prompt)
        if not response:
            self.log_callback("[Brain] No response from Claude, keeping current goal.")
        elif response.startswith("__ERROR__"):
            self.log_callback(f"[Brain] Claude CLI failed: {response[10:150]}")
        else:
            self._current_goal = response.strip()
            self.knowledge.set_goal(self._current_goal, priority=0, source="brain")
            self.log_callback(f"[Brain] New goal: {self._current_goal}")
            logger.info("Brain goal updated: %s", self._current_goal[:100])

    def _process_wiki_queue(self) -> None:
        while not self._wiki_queue.empty():
            try:
                topic = self._wiki_queue.get_nowait()
            except queue.Empty:
                break
            prompt = build_wiki_request(topic)
            self.log_callback(f"[Brain] Looking up wiki: {topic}")
            response = self.claude.query(prompt)
            if response and not response.startswith("__ERROR__"):
                self.knowledge.add_wiki(topic, response)
                self.log_callback(f"[Brain] Wiki: {topic}")
                self.log_callback(f"[Brain] Answer: {response}")
            elif response:
                self.log_callback(f"[Brain] Wiki failed: {response[10:150]}")
            self._wiki_queue.task_done()

    def _summarize_experience(self) -> None:
        """Feature B: summarize recent experience and save to wiki."""
        observations = self.knowledge.get_recent_observations(limit=50)
        if not observations:
            return
        controls = self.knowledge.get_controls(min_confidence=0.3)
        prompt = build_summary_request(observations, controls)
        self.log_callback("[Brain] 경험 요약 중...")

        response = self.claude.query(prompt)
        if not response:
            self.log_callback("[Brain] 경험 요약: Claude 응답 없음")
            return
        if response.startswith("__ERROR__"):
            self.log_callback(f"[Brain] 경험 요약 실패: {response[10:150]}")
            return

        self._summary_count += 1
        topic = f"경험요약_{self._summary_count}"
        self.knowledge.add_wiki(topic, response.strip(), source="brain_summary")
        self.log_callback(f"[Brain] 경험 요약 완료 → {topic}")
        logger.info("Brain experience summary saved: %s", topic)

    def _loop(self) -> None:
        logger.info("Brain loop started.")
        self.log_callback("[Brain] Loop started.")
        while self._running:
            now = time.time()
            if now - self.last_update_time >= self.goal_interval:
                try:
                    self._update_goal()
                except Exception as e:
                    logger.error("Brain goal update error: %s", e)
                    self.log_callback(f"[Brain] Error: {e}")
                self.last_update_time = time.time()

            # Feature B: periodic experience summary
            now = time.time()
            if now - self._last_summary_time >= self.summary_interval:
                try:
                    self._summarize_experience()
                except Exception as e:
                    logger.error("Brain summary error: %s", e)
                    self.log_callback(f"[Brain] Summary error: {e}")
                self._last_summary_time = time.time()

            try:
                self._process_wiki_queue()
            except Exception as e:
                logger.error("Brain wiki processing error: %s", e)
            time.sleep(1)
        logger.info("Brain loop stopped.")
        self.log_callback("[Brain] Loop stopped.")

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.last_update_time = 0
        self._thread = threading.Thread(target=self._loop, daemon=True, name="BrainThread")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    @property
    def is_running(self) -> bool:
        return self._running
