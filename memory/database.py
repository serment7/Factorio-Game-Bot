"""SQLite schema creation and connection management."""

import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "factorio_agent.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS known_controls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    context TEXT NOT NULL DEFAULT '',
    effect TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.5,
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_confirmed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    times_confirmed INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    screenshot_hash TEXT NOT NULL,
    thought TEXT NOT NULL DEFAULT '',
    action_type TEXT NOT NULL DEFAULT '',
    action_args TEXT NOT NULL DEFAULT '',
    result_hash TEXT,
    success INTEGER,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS wiki_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'brain',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_text TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    source TEXT NOT NULL DEFAULT 'brain',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS known_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    times_seen INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS known_recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    output_item TEXT NOT NULL,
    input_items TEXT NOT NULL DEFAULT '',
    crafting_method TEXT NOT NULL DEFAULT '',
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    confirmed INTEGER NOT NULL DEFAULT 0
);
"""


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path | None = None) -> None:
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        logger.info("Database initialized at %s", db_path or DB_PATH)
    finally:
        conn.close()


def reset_db(db_path: Path | None = None) -> None:
    conn = get_connection(db_path)
    try:
        tables = [
            "known_controls", "observations", "wiki_entries",
            "goals", "known_entities", "known_recipes",
        ]
        for table in tables:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        logger.info("Database reset at %s", db_path or DB_PATH)
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    print("Tables created. Testing reset...")
    reset_db()
    print("Reset complete. Verifying tables...")
    conn = get_connection()
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row["name"] for row in cursor.fetchall()]
    conn.close()
    print(f"Tables: {tables}")
