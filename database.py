import sqlite3
import os
import logging
from datetime import datetime
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "sanbot.db")

logger = logging.getLogger(__name__)


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY,
                message_id  TEXT UNIQUE NOT NULL,
                user_id     TEXT NOT NULL,
                username    TEXT NOT NULL,
                channel_id  TEXT NOT NULL,
                guild_id    TEXT NOT NULL,
                content     TEXT NOT NULL,
                timestamp   TEXT NOT NULL,
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_messages_user_id  ON messages(user_id);
            CREATE INDEX IF NOT EXISTS idx_messages_guild_id ON messages(guild_id);

            CREATE TABLE IF NOT EXISTS harvest_state (
                id              INTEGER PRIMARY KEY,
                user_id         TEXT NOT NULL,
                channel_id      TEXT NOT NULL,
                last_message_id TEXT,
                total_harvested INTEGER DEFAULT 0,
                last_run        TEXT,
                UNIQUE(user_id, channel_id)
            );

            CREATE TABLE IF NOT EXISTS training_runs (
                id          INTEGER PRIMARY KEY,
                started_at  TEXT NOT NULL,
                finished_at TEXT,
                message_count INTEGER,
                model_type  TEXT NOT NULL,
                status      TEXT DEFAULT 'running'
            );
        """)
    logger.info("Database initialised at %s", DB_PATH)


def insert_messages(rows: list[dict]) -> int:
    """Bulk-insert messages, ignoring duplicates. Returns count of new rows."""
    if not rows:
        return 0
    with get_connection() as conn:
        result = conn.executemany(
            """
            INSERT OR IGNORE INTO messages
                (message_id, user_id, username, channel_id, guild_id, content, timestamp)
            VALUES
                (:message_id, :user_id, :username, :channel_id, :guild_id, :content, :timestamp)
            """,
            rows,
        )
        return result.rowcount


def get_all_messages_for_user(user_id: str, guild_id: Optional[str] = None) -> list[str]:
    query = "SELECT content FROM messages WHERE user_id = ?"
    params: list = [user_id]
    if guild_id:
        query += " AND guild_id = ?"
        params.append(guild_id)
    query += " ORDER BY timestamp ASC"
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [r["content"] for r in rows]


def get_message_count(user_id: Optional[str] = None) -> int:
    with get_connection() as conn:
        if user_id:
            return conn.execute(
                "SELECT COUNT(*) FROM messages WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]


def update_harvest_state(user_id: str, channel_id: str, last_message_id: str, count: int):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO harvest_state (user_id, channel_id, last_message_id, total_harvested, last_run)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(user_id, channel_id) DO UPDATE SET
                last_message_id = excluded.last_message_id,
                total_harvested = harvest_state.total_harvested + excluded.total_harvested,
                last_run = excluded.last_run
            """,
            (user_id, channel_id, last_message_id, count),
        )


def get_harvest_state(user_id: str, channel_id: str) -> Optional[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM harvest_state WHERE user_id = ? AND channel_id = ?",
            (user_id, channel_id),
        ).fetchone()


def log_training_start(model_type: str) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO training_runs (started_at, model_type) VALUES (datetime('now'), ?)",
            (model_type,),
        )
        return cur.lastrowid


def log_training_finish(run_id: int, message_count: int, status: str = "done"):
    with get_connection() as conn:
        conn.execute(
            "UPDATE training_runs SET finished_at = datetime('now'), message_count = ?, status = ? WHERE id = ?",
            (message_count, status, run_id),
        )
