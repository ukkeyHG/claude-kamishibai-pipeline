"""
SQLite state management for the pipeline.

Handles episode creation, step tracking, checkpoints, and resume capability.
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .config import DB_PATH, PROJECT_ROOT


def _get_conn() -> sqlite3.Connection:
    """Get a database connection, creating the DB if needed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Initialize the database schema."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            episode_slug TEXT NOT NULL UNIQUE,
            country_ja TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'running',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            episode_id INTEGER NOT NULL REFERENCES episodes(id),
            step_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            retry_count INTEGER NOT NULL DEFAULT 0,
            timeout_sec INTEGER,
            output_file TEXT,
            checkpoint_value INTEGER,
            completed_at TEXT,
            error_message TEXT,
            generation_attempt INTEGER NOT NULL DEFAULT 1,
            UNIQUE(episode_id, step_name)
        );

        CREATE TABLE IF NOT EXISTS pipeline_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_steps_episode ON steps(episode_id, step_name);
        CREATE INDEX IF NOT EXISTS idx_steps_status ON steps(episode_id, status);
    """)
    
    # Safe column additions for existing schema
    try:
        conn.execute("ALTER TABLE steps ADD COLUMN updated_at TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE steps ADD COLUMN started_at TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE steps ADD COLUMN tokens_in INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE steps ADD COLUMN tokens_out INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE steps ADD COLUMN active_agent TEXT DEFAULT 'pipeline'")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE steps ADD COLUMN generation_attempt INTEGER NOT NULL DEFAULT 1")
    except sqlite3.OperationalError:
        pass
        
    conn.commit()
    conn.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


# ---------------------------------------------------------------------------
# Episode management
# ---------------------------------------------------------------------------

def create_episode(episode_slug: str, country_ja: str) -> int:
    """Create a new episode record. Returns episode_id."""
    conn = _get_conn()
    try:
        now = _now_iso()
        conn.execute(
            "INSERT INTO episodes (episode_slug, country_ja, status, created_at, updated_at) VALUES (?, ?, 'running', ?, ?)",
            (episode_slug, country_ja, now, now),
        )
        conn.commit()
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    finally:
        conn.close()


def get_episode(episode_slug: str) -> dict | None:
    """Get episode by slug."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM episodes WHERE episode_slug = ?", (episode_slug,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_episode_status(episode_slug: str, status: str) -> None:
    """Update episode status (running/completed/aborted)."""
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE episodes SET status = ?, updated_at = ? WHERE episode_slug = ?",
            (status, _now_iso(), episode_slug),
        )
        if status in ("aborted", "failed"):
            episode = conn.execute(
                "SELECT id FROM episodes WHERE episode_slug = ?", (episode_slug,)
            ).fetchone()
            if episode:
                conn.execute(
                    "UPDATE steps SET status = 'failed' WHERE episode_id = ? AND status IN ('running', 'pending')",
                    (episode["id"],)
                )
        conn.commit()
    finally:
        conn.close()


def delete_episode_from_db(episode_slug: str) -> None:
    """Completely delete an episode and its steps from the database."""
    conn = _get_conn()
    try:
        episode = conn.execute(
            "SELECT id FROM episodes WHERE episode_slug = ?", (episode_slug,)
        ).fetchone()
        if episode:
            episode_id = episode["id"]
            conn.execute("DELETE FROM steps WHERE episode_id = ?", (episode_id,))
            conn.execute("DELETE FROM episodes WHERE id = ?", (episode_id,))
            # Also clear the global checkpoint so the pipeline doesn't resume a deleted state
            conn.execute("DELETE FROM pipeline_state WHERE key = 'checkpoint'")
            conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Step management
# ---------------------------------------------------------------------------

def create_step(
    episode_id: int,
    step_name: str,
    output_file: str | None = None,
    timeout_sec: int | None = None,
    checkpoint_value: int | None = None,
) -> int:
    """Create a step record. Returns step_id."""
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO steps
               (episode_id, step_name, status, output_file, timeout_sec, checkpoint_value, started_at, active_agent, generation_attempt)
               VALUES (?, ?, 'pending', ?, ?, ?, ?, 'pipeline', 1)""",
            (episode_id, step_name, output_file, timeout_sec, checkpoint_value, _now_iso()),
        )
        conn.commit()
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    finally:
        conn.close()


def get_step(episode_id: int, step_name: str) -> dict | None:
    """Get a step by episode_id and step_name."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM steps WHERE episode_id = ? AND step_name = ?",
            (episode_id, step_name),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_step_status(
    episode_id: int,
    step_name: str,
    status: str,
    error_message: str | None = None,
) -> None:
    """Update step status."""
    conn = _get_conn()
    try:
        conn.execute(
            """UPDATE steps SET status = ?, updated_at = ?, error_message = ?
               WHERE episode_id = ? AND step_name = ?""",
            (status, _now_iso(), error_message, episode_id, step_name),
        )
        conn.commit()
    finally:
        conn.close()


def reset_step_for_resume(episode_id: int, step_name: str) -> None:
    """Reset a failed/aborted step to pending with fresh timestamps and counters."""
    conn = _get_conn()
    try:
        conn.execute(
            """UPDATE steps 
               SET status = 'pending',
                   updated_at = ?,
                   started_at = ?,
                   completed_at = NULL,
                   error_message = NULL,
                   retry_count = 0,
                   tokens_in = 0,
                   tokens_out = 0,
                   active_agent = 'pipeline'
               WHERE episode_id = ? AND step_name = ?""",
            (_now_iso(), _now_iso(), episode_id, step_name),
        )
        conn.commit()
    finally:
        conn.close()


def set_generation_attempt(episode_id: int, step_name: str, attempt: int) -> None:
    """Update the current generation attempt count."""
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE steps SET generation_attempt = ? WHERE episode_id = ? AND step_name = ?",
            (attempt, episode_id, step_name)
        )
        conn.commit()
    finally:
        conn.close()


def complete_step(
    episode_id: int,
    step_name: str,
    retry_count: int = 0,
) -> None:
    """Mark a step as completed."""
    conn = _get_conn()
    try:
        conn.execute(
            """UPDATE steps SET status = 'completed', retry_count = ?, completed_at = ?
               WHERE episode_id = ? AND step_name = ?""",
            (retry_count, _now_iso(), episode_id, step_name),
        )
        conn.commit()
    finally:
        conn.close()


def increment_retry(episode_id: int, step_name: str) -> int:
    """Increment retry count and return new count."""
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE steps SET retry_count = retry_count + 1, status = 'running' WHERE episode_id = ? AND step_name = ?",
            (episode_id, step_name),
        )
        conn.commit()
        row = conn.execute(
            "SELECT retry_count FROM steps WHERE episode_id = ? AND step_name = ?",
            (episode_id, step_name),
        ).fetchone()
        return row["retry_count"] if row else 0
    finally:
        conn.close()


def get_pending_steps(episode_id: int) -> list[dict]:
    """Get all pending steps for an episode, ordered by step_name order."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT s.*, ep.episode_slug, ep.country_ja
               FROM steps s
               JOIN episodes ep ON s.episode_id = ep.id
               WHERE s.episode_id = ? AND s.status = 'pending'
               ORDER BY s.step_name""",
            (episode_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Checkpoint management
# ---------------------------------------------------------------------------

def set_checkpoint(episode_slug: str, value: int) -> None:
    """Set the pipeline checkpoint (last completed step)."""
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO pipeline_state (key, value) VALUES ('checkpoint', ?)",
            (str(value),),
        )
        conn.commit()
    finally:
        conn.close()


def get_checkpoint(episode_slug: str) -> Optional[int]:
    """Get the pipeline checkpoint value from database."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT value FROM pipeline_state WHERE key = 'checkpoint'"
        ).fetchone()
        return int(row["value"]) if row else None
    finally:
        conn.close()


def clear_checkpoint(episode_slug: str) -> None:
    """Clear the pipeline checkpoint."""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM pipeline_state WHERE key = 'checkpoint'")
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Resume logic
# ---------------------------------------------------------------------------

def get_resume_info(episode_slug: str) -> dict | None:
    """Check if there's a resume-able episode. Returns info or None."""
    episode = get_episode(episode_slug)
    if not episode:
        return None

    checkpoint = get_checkpoint(episode_slug)
    if checkpoint is None and episode["status"] == "completed":
        return None  # Fully completed, no resume needed

    return {
        "episode": episode,
        "checkpoint": checkpoint,
        "is_resume": checkpoint is not None or episode["status"] != "completed",
    }


def get_next_step(episode_id: int, current_checkpoint: int | None) -> dict | None:
    """Get the next step to execute based on checkpoint."""
    if current_checkpoint is None:
        # Fresh start: get first pending step
        steps = get_pending_steps(episode_id)
        return steps[0] if steps else None

    # Resume: find first pending step after checkpoint
    steps = get_pending_steps(episode_id)
    for step in steps:
        if step.get("checkpoint_value", 0) > current_checkpoint:
            return step

    # All steps after checkpoint are done; check for remaining pending
    return steps[0] if steps else None


# ---------------------------------------------------------------------------
# Logging helpers (replaces log_progress.sh)
# ---------------------------------------------------------------------------




def update_active_step_metrics(episode_slug: str, agent: str, tokens: dict | None) -> None:
    """Update agent and token metrics for the currently running/pending step."""
    conn = _get_conn()
    try:
        episode = conn.execute("SELECT id FROM episodes WHERE episode_slug = ?", (episode_slug,)).fetchone()
        if not episode:
            return
            
        episode_id = episode["id"]
        
        if tokens:
            conn.execute(
                """UPDATE steps 
                   SET active_agent = ?, tokens_in = tokens_in + ?, tokens_out = tokens_out + ?
                   WHERE episode_id = ? AND status IN ('running', 'pending')""",
                (agent, tokens.get("in", 0), tokens.get("out", 0), episode_id)
            )
        else:
            conn.execute(
                """UPDATE steps 
                   SET active_agent = ?
                   WHERE episode_id = ? AND status IN ('running', 'pending')""",
                (agent, episode_id)
            )
        conn.commit()
    finally:
        conn.close()

def append_jsonl_log(
    episode_slug: str,
    agent: str,
    phase: str,
    message: str,
    step: str | None = None,
    tokens: dict | None = None,
) -> None:
    """Append to status.log.jsonl (replaces log_progress.sh part 2)."""
    ep_dir = PROJECT_ROOT / "episodes" / episode_slug
    ep_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = ep_dir / "status.log.jsonl"

    entry = {
        "ts": _now_iso(),
        "agent": agent,
        "phase": phase,
        "message": message,
    }
    if step:
        entry["step"] = step
    if tokens:
        entry["tokens"] = tokens

    with open(jsonl_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def log_progress(
    episode_slug: str,
    country_ja: str,
    agent: str,
    phase: str,
    message: str,
    step: str | None = None,
    tokens: dict | None = None,
) -> None:
    """Log pipeline progress directly to status.log.jsonl and update DB metrics."""
    append_jsonl_log(episode_slug, agent, phase, message, step, tokens)
    update_active_step_metrics(episode_slug, agent, tokens)
