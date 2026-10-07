"""SQLite storage. One connection per unit of work; WAL mode so the UI can read while a run writes."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    keywords TEXT NOT NULL,              -- JSON list of search terms
    sources TEXT NOT NULL,               -- JSON list of source keys
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    fingerprint TEXT NOT NULL UNIQUE,    -- normalised title + company, used to merge duplicates across sources
    title TEXT NOT NULL,
    company TEXT,
    location TEXT,
    description TEXT,                    -- plain text
    posted_at TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    employment_raw TEXT,
    salary_text TEXT,
    category TEXT,
    seniority TEXT,
    job_type TEXT,
    class_source TEXT DEFAULT 'rules',   -- 'rules' or 'ai'
    closed INTEGER NOT NULL DEFAULT 0,
    ai_status TEXT NOT NULL DEFAULT 'pending',  -- pending | done | error
    ai_error TEXT,
    ai_data TEXT,
    ai_model TEXT,
    ai_analyzed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_last_seen ON jobs(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_jobs_cat ON jobs(category, seniority);

CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    url TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    detail_fetched INTEGER NOT NULL DEFAULT 0,
    UNIQUE(source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_listings_job ON listings(job_id);

CREATE TABLE IF NOT EXISTS job_searches (
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    search_id INTEGER NOT NULL REFERENCES searches(id) ON DELETE CASCADE,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (job_id, search_id)
);

CREATE TABLE IF NOT EXISTS job_skills (
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    skill TEXT NOT NULL,
    skill_type TEXT,
    required INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (job_id, skill)
);
CREATE INDEX IF NOT EXISTS idx_job_skills_skill ON job_skills(skill);

CREATE TABLE IF NOT EXISTS job_languages (
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    language TEXT NOT NULL,
    level TEXT,
    required INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (job_id, language)
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,                  -- collect | analyze
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,                -- running | done | failed | cancelled
    stats TEXT,
    log TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS summaries (
    key TEXT PRIMARY KEY,
    job_count INTEGER NOT NULL,
    content TEXT NOT NULL,
    model TEXT,
    created_at TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "linkedin_mode": "public",           # public | logged_in
    "linkedin_show_browser": "0",
    "linkedin_max_pages": "10",          # guest: 10 results per page; logged in: 25 per page
    "linkedin_posted_within_days": "30",
    "karriere_max_pages": "20",          # ~15 results per page
    "adzuna_max_pages": "4",             # 50 results per page
    "active_window_days": "14",
    "ai_provider": "anthropic",           # anthropic | openai
    "ai_model": config.DEFAULT_AI_MODEL,  # Anthropic model
    "openai_model": config.DEFAULT_OPENAI_MODEL,
    "ai_auto_analyze": "1",
    "ai_concurrency": "4",
    "planning_model": "",                 # provider:model for profile analysis + roadmaps; "" = best available
    "planning_effort": "high",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path: Optional[str] = None) -> sqlite3.Connection:
    db_path = path or str(config.DB_PATH)
    if db_path != ":memory:":
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def session() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(conn: Optional[sqlite3.Connection] = None) -> None:
    own = conn is None
    conn = conn or connect()
    try:
        conn.executescript(SCHEMA)
        from . import planner, profile  # local import: those modules import db

        profile.ensure_table(conn)
        planner.ensure_tables(conn)
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))
        if conn.execute("SELECT COUNT(*) FROM searches").fetchone()[0] == 0:
            for name, keywords in config.DEFAULT_SEARCHES:
                conn.execute(
                    "INSERT INTO searches(name, keywords, sources, enabled, created_at) VALUES (?,?,?,?,?)",
                    (name, json.dumps(keywords), json.dumps(["karriere", "linkedin", "adzuna"]), 1, now_iso()),
                )
        # A run left "running" by a crash or restart can never finish.
        conn.execute("UPDATE runs SET status='failed', finished_at=? WHERE status='running'", (now_iso(),))
        conn.commit()
    finally:
        if own:
            conn.close()


def get_settings(conn: sqlite3.Connection) -> dict[str, str]:
    values = dict(DEFAULT_SETTINGS)
    values.update({r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")})
    return values


def set_setting(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )


def int_setting(settings: dict[str, str], key: str) -> int:
    try:
        return int(settings.get(key) or DEFAULT_SETTINGS[key])
    except ValueError:
        return int(DEFAULT_SETTINGS[key])
