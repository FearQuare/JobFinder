"""Database reads/writes for jobs and listings."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from . import classify, db
from .sources.base import RawJob


def _better_description(old: Optional[str], new: Optional[str], new_is_full: bool, old_is_full: bool) -> bool:
    if not new:
        return False
    if not old:
        return True
    if new_is_full and not old_is_full:
        return True
    if old_is_full and not new_is_full:
        return False
    return len(new) > len(old)


def _job_has_full_description(conn: sqlite3.Connection, job_id: int) -> bool:
    row = conn.execute("SELECT 1 FROM listings WHERE job_id=? AND detail_fetched=1 LIMIT 1", (job_id,)).fetchone()
    return row is not None


def upsert_listing(conn: sqlite3.Connection, raw: RawJob, search_id: Optional[int], supports_detail: bool) -> Tuple[int, bool, bool]:
    """Store a job seen in search results. Returns (job_id, is_new_job, needs_detail)."""
    now = db.now_iso()
    listing = conn.execute("SELECT * FROM listings WHERE source=? AND source_id=?", (raw.source, raw.source_id)).fetchone()
    is_new_job = False
    if listing:
        job_id = listing["job_id"]
        conn.execute("UPDATE listings SET last_seen_at=?, url=COALESCE(NULLIF(?, ''), url) WHERE id=?", (now, raw.url, listing["id"]))
        conn.execute("UPDATE jobs SET last_seen_at=? WHERE id=?", (now, job_id))
        needs_detail = supports_detail and not listing["detail_fetched"]
    else:
        fp = classify.fingerprint(raw.title, raw.company)
        job = conn.execute("SELECT id FROM jobs WHERE fingerprint=?", (fp,)).fetchone()
        if job:
            job_id = job["id"]
            conn.execute("UPDATE jobs SET last_seen_at=? WHERE id=?", (now, job_id))
            _merge_basic_fields(conn, job_id, raw)
        else:
            c = classify.classify(raw.title, raw.employment_raw, raw.seniority_raw)
            cur = conn.execute(
                """INSERT INTO jobs(fingerprint, title, company, location, description, posted_at, first_seen_at, last_seen_at,
                                    employment_raw, salary_text, category, seniority, job_type, class_source, closed)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'rules', ?)""",
                (fp, raw.title, raw.company, raw.location, raw.description, raw.posted_at, now, now,
                 raw.employment_raw, raw.salary_text, c["category"], c["seniority"], c["job_type"], int(raw.closed)),
            )
            job_id = cur.lastrowid
            is_new_job = True
        conn.execute(
            "INSERT INTO listings(job_id, source, source_id, url, first_seen_at, last_seen_at, detail_fetched) VALUES (?,?,?,?,?,?,?)",
            (job_id, raw.source, raw.source_id, raw.url, now, now, int(raw.description_is_full or not supports_detail)),
        )
        needs_detail = supports_detail and not raw.description_is_full
    if search_id is not None:
        conn.execute(
            "INSERT INTO job_searches(job_id, search_id, last_seen_at) VALUES (?,?,?) "
            "ON CONFLICT(job_id, search_id) DO UPDATE SET last_seen_at=excluded.last_seen_at",
            (job_id, search_id, now),
        )
    return job_id, is_new_job, needs_detail


def _merge_basic_fields(conn: sqlite3.Connection, job_id: int, raw: RawJob) -> None:
    job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    updates: Dict[str, Any] = {}
    for field in ("company", "location", "posted_at", "employment_raw", "salary_text"):
        if not job[field] and getattr(raw, field):
            updates[field] = getattr(raw, field)
    if _better_description(job["description"], raw.description, raw.description_is_full, _job_has_full_description(conn, job_id)):
        updates["description"] = raw.description
    if updates:
        sets = ", ".join(f"{k}=?" for k in updates)
        conn.execute(f"UPDATE jobs SET {sets} WHERE id=?", (*updates.values(), job_id))


def apply_detail(conn: sqlite3.Connection, raw: RawJob) -> Optional[int]:
    """Store the full description etc. fetched from a job's detail page."""
    listing = conn.execute("SELECT * FROM listings WHERE source=? AND source_id=?", (raw.source, raw.source_id)).fetchone()
    if not listing:
        return None
    job_id = listing["job_id"]
    job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    had_full = _job_has_full_description(conn, job_id)
    updates: Dict[str, Any] = {}
    if _better_description(job["description"], raw.description, raw.description_is_full, had_full):
        updates["description"] = raw.description
        if job["ai_status"] == "done" and not had_full:
            updates["ai_status"] = "pending"  # re-analyse now that the full text is available
    for field in ("company", "location", "posted_at", "employment_raw", "salary_text"):
        if getattr(raw, field) and (not job[field] or field in ("posted_at", "employment_raw")):
            updates[field] = getattr(raw, field)
    if raw.closed:
        updates["closed"] = 1
    if job["class_source"] == "rules":
        c = classify.classify(job["title"], raw.employment_raw or job["employment_raw"], raw.seniority_raw)
        updates.update(c)
    if updates:
        sets = ", ".join(f"{k}=?" for k in updates)
        conn.execute(f"UPDATE jobs SET {sets} WHERE id=?", (*updates.values(), job_id))
    conn.execute("UPDATE listings SET detail_fetched=1 WHERE id=?", (listing["id"],))
    return job_id


def known_listing(conn: sqlite3.Connection, source: str, source_id: str) -> bool:
    return conn.execute("SELECT 1 FROM listings WHERE source=? AND source_id=?", (source, source_id)).fetchone() is not None


# ---------- AI results ----------

def save_ai_result(conn: sqlite3.Connection, job_id: int, result: dict, model: str) -> None:
    conn.execute("DELETE FROM job_skills WHERE job_id=?", (job_id,))
    conn.execute("DELETE FROM job_languages WHERE job_id=?", (job_id,))
    for s in result.get("skills", []):
        conn.execute(
            "INSERT OR REPLACE INTO job_skills(job_id, skill, skill_type, required) VALUES (?,?,?,?)",
            (job_id, s["name"], s.get("type"), int(bool(s.get("required", True)))),
        )
    for l in result.get("languages", []):
        conn.execute(
            "INSERT OR REPLACE INTO job_languages(job_id, language, level, required) VALUES (?,?,?,?)",
            (job_id, l["language"], l.get("level"), int(bool(l.get("required", True)))),
        )
    conn.execute(
        """UPDATE jobs SET category=?, seniority=?, job_type=?, class_source='ai', ai_status='done', ai_error=NULL,
                           ai_data=?, ai_model=?, ai_analyzed_at=? WHERE id=?""",
        (result["category"], result["seniority"], result["job_type"], json.dumps(result), model, db.now_iso(), job_id),
    )


def save_ai_error(conn: sqlite3.Connection, job_id: int, error: str) -> None:
    conn.execute("UPDATE jobs SET ai_status='error', ai_error=? WHERE id=?", (error[:500], job_id))


# ---------- queries for the UI ----------

def active_cutoff(conn: sqlite3.Connection, window_days: int) -> Optional[str]:
    """Jobs seen within `window_days` of the most recent sighting count as currently open.

    Measured from the latest collection rather than from today, so jobs don't all
    disappear just because you haven't collected for a while.
    """
    row = conn.execute("SELECT MAX(last_seen_at) FROM jobs").fetchone()
    if not row or not row[0]:
        return None
    latest = datetime.fromisoformat(row[0])
    return (latest - timedelta(days=window_days)).isoformat()


def build_job_filters(conn: sqlite3.Connection, f: Dict[str, Any], window_days: int) -> Tuple[str, List[Any]]:
    where = ["1=1"]
    params: List[Any] = []
    if f.get("status", "open") == "open":
        cutoff = active_cutoff(conn, window_days)
        where.append("j.closed=0")
        if cutoff:
            where.append("j.last_seen_at >= ?")
            params.append(cutoff)
    if f.get("search_id"):
        where.append("j.id IN (SELECT job_id FROM job_searches WHERE search_id=?)")
        params.append(int(f["search_id"]))
    for key in ("category", "seniority", "job_type"):
        if f.get(key):
            where.append(f"j.{key}=?")
            params.append(f[key])
    if not f.get("category") and f.get("hide_other", True):
        where.append("COALESCE(j.category,'') != 'other'")
    if f.get("source"):
        where.append("j.id IN (SELECT job_id FROM listings WHERE source=?)")
        params.append(f["source"])
    if f.get("skill"):
        where.append("j.id IN (SELECT job_id FROM job_skills WHERE skill=?)")
        params.append(f["skill"])
    if f.get("q"):
        for term in str(f["q"]).split():
            where.append("(j.title LIKE ? OR j.company LIKE ? OR j.description LIKE ? OR j.location LIKE ?)")
            params.extend([f"%{term}%"] * 4)
    if f.get("location"):
        where.append("j.location LIKE ?")
        params.append(f"%{f['location']}%")
    if f.get("posted_days"):
        cutoff = (datetime.now() - timedelta(days=int(f["posted_days"]))).date().isoformat()
        where.append("COALESCE(j.posted_at, substr(j.first_seen_at,1,10)) >= ?")
        params.append(cutoff)
    return " AND ".join(where), params


def list_jobs(conn: sqlite3.Connection, f: Dict[str, Any], window_days: int, page: int = 1, per_page: int = 50) -> Tuple[List[sqlite3.Row], int]:
    where, params = build_job_filters(conn, f, window_days)
    total = conn.execute(f"SELECT COUNT(*) FROM jobs j WHERE {where}", params).fetchone()[0]
    order = {
        "posted": "COALESCE(j.posted_at, substr(j.first_seen_at,1,10)) DESC, j.id DESC",
        "found": "j.first_seen_at DESC, j.id DESC",
        "company": "j.company COLLATE NOCASE, j.title",
    }.get(f.get("sort") or "posted") or "COALESCE(j.posted_at, substr(j.first_seen_at,1,10)) DESC, j.id DESC"
    rows = conn.execute(
        f"""SELECT j.*, (SELECT GROUP_CONCAT(source || '|' || COALESCE(url,''), '\n') FROM listings l WHERE l.job_id=j.id) AS listing_info
            FROM jobs j WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?""",
        (*params, per_page, (page - 1) * per_page),
    ).fetchall()
    return rows, total


def job_listings(conn: sqlite3.Connection, job_id: int) -> List[sqlite3.Row]:
    return conn.execute("SELECT * FROM listings WHERE job_id=? ORDER BY source", (job_id,)).fetchall()


def dashboard_counts(conn: sqlite3.Connection, window_days: int) -> dict:
    cutoff = active_cutoff(conn, window_days) or "0000"
    row = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN closed=0 AND last_seen_at>=? THEN 1 ELSE 0 END) AS open,
                  SUM(CASE WHEN ai_status='done' THEN 1 ELSE 0 END) AS analysed,
                  SUM(CASE WHEN ai_status IN ('pending','error') AND closed=0 AND last_seen_at>=? THEN 1 ELSE 0 END) AS pending
           FROM jobs""",
        (cutoff, cutoff),
    ).fetchone()
    return {k: (row[k] or 0) for k in row.keys()}


def list_job_ids(conn: sqlite3.Connection, f: Dict[str, Any], window_days: int) -> List[int]:
    where, params = build_job_filters(conn, f, window_days)
    return [r[0] for r in conn.execute(f"SELECT j.id FROM jobs j WHERE {where}", params)]


def jobs_by_ids(conn: sqlite3.Connection, ids: List[int]) -> List[sqlite3.Row]:
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"""SELECT j.*, (SELECT GROUP_CONCAT(source || '|' || COALESCE(url,''), '\n') FROM listings l WHERE l.job_id=j.id) AS listing_info
            FROM jobs j WHERE j.id IN ({marks})""", ids).fetchall()
    order = {jid: i for i, jid in enumerate(ids)}
    return sorted(rows, key=lambda r: order[r["id"]])
