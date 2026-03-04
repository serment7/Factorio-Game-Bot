"""CRUD operations for all 6 learning tables."""

import sqlite3
import logging
from typing import Any

from memory.database import get_connection

logger = logging.getLogger(__name__)


class KnowledgeStore:
    """Manages all learning data CRUD operations."""

    def __init__(self, conn: sqlite3.Connection | None = None):
        self._conn = conn or get_connection()

    def close(self):
        self._conn.close()

    # --- known_controls ---

    def add_control(self, key: str, context: str, effect: str, confidence: float = 0.5) -> int:
        """Record a discovered control. Returns row id."""
        cur = self._conn.execute(
            "SELECT id, times_confirmed FROM known_controls WHERE key = ? AND context = ?",
            (key, context),
        )
        row = cur.fetchone()
        if row:
            new_conf = min(1.0, confidence + 0.1)
            self._conn.execute(
                "UPDATE known_controls SET effect = ?, confidence = ?, "
                "last_confirmed = CURRENT_TIMESTAMP, times_confirmed = ? WHERE id = ?",
                (effect, new_conf, row["times_confirmed"] + 1, row["id"]),
            )
            self._conn.commit()
            return row["id"]
        cur = self._conn.execute(
            "INSERT INTO known_controls (key, context, effect, confidence) VALUES (?, ?, ?, ?)",
            (key, context, effect, confidence),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_controls(self, min_confidence: float = 0.0) -> list[dict[str, Any]]:
        """Get all known controls above confidence threshold."""
        cur = self._conn.execute(
            "SELECT * FROM known_controls WHERE confidence >= ? ORDER BY confidence DESC",
            (min_confidence,),
        )
        return [dict(r) for r in cur.fetchall()]

    # --- observations ---

    def add_observation(
        self, screenshot_hash: str, thought: str, action_type: str,
        action_args: str, result_hash: str | None = None, success: int | None = None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO observations (screenshot_hash, thought, action_type, action_args, result_hash, success) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (screenshot_hash, thought, action_type, action_args, result_hash, success),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_recent_observations(self, limit: int = 10) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT * FROM observations ORDER BY timestamp DESC LIMIT ?", (limit,),
        )
        return [dict(r) for r in cur.fetchall()]

    # --- wiki_entries ---

    def add_wiki(self, topic: str, content: str, source: str = "brain") -> int:
        cur = self._conn.execute(
            "INSERT INTO wiki_entries (topic, content, source) VALUES (?, ?, ?) "
            "ON CONFLICT(topic) DO UPDATE SET content = ?, updated_at = CURRENT_TIMESTAMP",
            (topic, content, source, content),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_wiki(self, topic: str) -> dict[str, Any] | None:
        cur = self._conn.execute("SELECT * FROM wiki_entries WHERE topic = ?", (topic,))
        row = cur.fetchone()
        return dict(row) if row else None

    def search_wiki(self, keyword: str) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT * FROM wiki_entries WHERE topic LIKE ? OR content LIKE ?",
            (f"%{keyword}%", f"%{keyword}%"),
        )
        return [dict(r) for r in cur.fetchall()]

    # --- goals ---

    def set_goal(self, goal_text: str, priority: int = 0, source: str = "brain") -> int:
        # Deactivate previous active goals from same source
        self._conn.execute(
            "UPDATE goals SET status = 'replaced' WHERE status = 'active' AND source = ?",
            (source,),
        )
        cur = self._conn.execute(
            "INSERT INTO goals (goal_text, priority, source) VALUES (?, ?, ?)",
            (goal_text, priority, source),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_active_goal(self) -> dict[str, Any] | None:
        cur = self._conn.execute(
            "SELECT * FROM goals WHERE status = 'active' ORDER BY priority DESC, created_at DESC LIMIT 1"
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def complete_goal(self, goal_id: int) -> None:
        self._conn.execute(
            "UPDATE goals SET status = 'completed', completed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (goal_id,),
        )
        self._conn.commit()

    # --- known_entities ---

    def add_entity(self, name: str, category: str = "", description: str = "") -> int:
        cur = self._conn.execute("SELECT id, times_seen FROM known_entities WHERE name = ?", (name,))
        row = cur.fetchone()
        if row:
            self._conn.execute(
                "UPDATE known_entities SET times_seen = ?, description = ? WHERE id = ?",
                (row["times_seen"] + 1, description or row["description"], row["id"]),
            )
            self._conn.commit()
            return row["id"]
        cur = self._conn.execute(
            "INSERT INTO known_entities (name, category, description) VALUES (?, ?, ?)",
            (name, category, description),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_entities(self, category: str | None = None) -> list[dict[str, Any]]:
        if category:
            cur = self._conn.execute(
                "SELECT * FROM known_entities WHERE category = ? ORDER BY times_seen DESC",
                (category,),
            )
        else:
            cur = self._conn.execute("SELECT * FROM known_entities ORDER BY times_seen DESC")
        return [dict(r) for r in cur.fetchall()]

    # --- known_recipes ---

    def add_recipe(self, output_item: str, input_items: str, crafting_method: str = "", confirmed: int = 0) -> int:
        cur = self._conn.execute(
            "SELECT id FROM known_recipes WHERE output_item = ? AND input_items = ?",
            (output_item, input_items),
        )
        row = cur.fetchone()
        if row:
            self._conn.execute(
                "UPDATE known_recipes SET confirmed = 1 WHERE id = ?", (row["id"],),
            )
            self._conn.commit()
            return row["id"]
        cur = self._conn.execute(
            "INSERT INTO known_recipes (output_item, input_items, crafting_method, confirmed) VALUES (?, ?, ?, ?)",
            (output_item, input_items, crafting_method, confirmed),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_recipes(self, confirmed_only: bool = False) -> list[dict[str, Any]]:
        if confirmed_only:
            cur = self._conn.execute("SELECT * FROM known_recipes WHERE confirmed = 1")
        else:
            cur = self._conn.execute("SELECT * FROM known_recipes")
        return [dict(r) for r in cur.fetchall()]

    # --- stats ---

    def get_stats(self) -> dict[str, int]:
        """Return counts for all tables."""
        stats = {}
        for table in ["known_controls", "observations", "wiki_entries", "goals", "known_entities", "known_recipes"]:
            cur = self._conn.execute(f"SELECT COUNT(*) as cnt FROM {table}")
            stats[table] = cur.fetchone()["cnt"]
        return stats
