"""Aggregate AI-extracted requirements into per-role reports."""
from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

from . import config, repo


def _group_where(conn: sqlite3.Connection, category: Optional[str], seniority: Optional[str], job_type: Optional[str],
                 window_days: int, search_id: Optional[int] = None) -> Tuple[str, list]:
    where = ["j.ai_status='done'", "j.closed=0"]
    params: list = []
    cutoff = repo.active_cutoff(conn, window_days)
    if cutoff:
        where.append("j.last_seen_at >= ?")
        params.append(cutoff)
    if category:
        where.append("j.category=?")
        params.append(category)
    else:
        where.append("j.category != 'other'")
    if seniority:
        where.append("j.seniority=?")
        params.append(seniority)
    if job_type:
        where.append("j.job_type=?")
        params.append(job_type)
    if search_id:
        where.append("j.id IN (SELECT job_id FROM job_searches WHERE search_id=?)")
        params.append(search_id)
    return " AND ".join(where), params


def group_stats(conn: sqlite3.Connection, category: Optional[str], seniority: Optional[str], job_type: Optional[str],
                window_days: int, search_id: Optional[int] = None, top_n: int = 40) -> Dict[str, Any]:
    where, params = _group_where(conn, category, seniority, job_type, window_days, search_id)
    jobs = conn.execute(f"SELECT j.id, j.ai_data FROM jobs j WHERE {where}", params).fetchall()
    n = len(jobs)
    result: Dict[str, Any] = {"job_count": n, "skills": [], "languages": [], "experience": {}, "education": {}, "remote": {}}
    if n == 0:
        return result

    skill_rows = conn.execute(
        f"SELECT s.skill, s.skill_type, s.required FROM job_skills s JOIN jobs j ON j.id=s.job_id WHERE {where}", params
    ).fetchall()
    counts: Counter = Counter()
    required: Counter = Counter()
    names: Dict[str, Counter] = defaultdict(Counter)
    types: Dict[str, Counter] = defaultdict(Counter)
    for r in skill_rows:
        k = r["skill"].lower()
        counts[k] += 1
        required[k] += r["required"]
        names[k][r["skill"]] += 1
        types[k][r["skill_type"]] += 1
    for k, c in counts.most_common(top_n):
        result["skills"].append({
            "skill": names[k].most_common(1)[0][0],
            "type": types[k].most_common(1)[0][0],
            "count": c,
            "pct": round(100 * c / n),
            "required_pct": round(100 * required[k] / c),
        })

    lang_rows = conn.execute(
        f"SELECT l.language, l.level, l.required FROM job_languages l JOIN jobs j ON j.id=l.job_id WHERE {where}", params
    ).fetchall()
    lang_counts: Counter = Counter()
    lang_levels: Dict[str, Counter] = defaultdict(Counter)
    for r in lang_rows:
        lang_counts[r["language"]] += 1
        lang_levels[r["language"]][_level_bucket(r["level"])] += 1
    for lang, c in lang_counts.most_common(6):
        result["languages"].append({
            "language": lang, "count": c, "pct": round(100 * c / n),
            "levels": dict(lang_levels[lang].most_common()),
        })

    years: List[int] = []
    edu: Counter = Counter()
    remote: Counter = Counter()
    for j in jobs:
        try:
            data = json.loads(j["ai_data"] or "{}")
        except ValueError:
            continue
        if isinstance(data.get("years_experience_min"), int):
            years.append(data["years_experience_min"])
        edu[data.get("education", "not_mentioned")] += 1
        remote[data.get("remote_policy", "not_mentioned")] += 1
    result["experience"] = {
        "stated_in": len(years),
        "median_years": median(years) if years else None,
        "buckets": _year_buckets(years),
    }
    result["education"] = dict(edu.most_common())
    result["remote"] = dict(remote.most_common())
    return result


def _level_bucket(level: Optional[str]) -> str:
    lvl = (level or "").strip().upper()
    for cefr in ("C2", "C1", "B2", "B1", "A2", "A1"):
        if cefr in lvl:
            return cefr
    if "NATIVE" in lvl or "MUTTER" in lvl:
        return "Native"
    return "Level not stated"


def _year_buckets(years: List[int]) -> Dict[str, int]:
    buckets = {"0-1": 0, "2-3": 0, "4-5": 0, "6+": 0}
    for y in years:
        if y <= 1:
            buckets["0-1"] += 1
        elif y <= 3:
            buckets["2-3"] += 1
        elif y <= 5:
            buckets["4-5"] += 1
        else:
            buckets["6+"] += 1
    return buckets


def overview(conn: sqlite3.Connection, window_days: int, job_type: Optional[str] = None, top_n: int = 6) -> List[Dict[str, Any]]:
    """One row per (category, seniority) group that has analysed jobs, with its top skills."""
    where, params = _group_where(conn, None, None, job_type, window_days)
    groups = conn.execute(
        f"SELECT j.category, j.seniority, COUNT(*) AS n FROM jobs j WHERE {where} GROUP BY j.category, j.seniority", params
    ).fetchall()
    order_cat = list(config.CATEGORIES)
    order_sen = list(config.SENIORITIES)
    out = []
    for g in sorted(groups, key=lambda g: (order_cat.index(g["category"]) if g["category"] in order_cat else 99,
                                             order_sen.index(g["seniority"]) if g["seniority"] in order_sen else 99)):
        stats = group_stats(conn, g["category"], g["seniority"], job_type, window_days, top_n=top_n)
        out.append({"category": g["category"], "seniority": g["seniority"], "job_count": g["n"], "skills": stats["skills"],
                    "languages": stats["languages"]})
    return out


def group_title(category: Optional[str], seniority: Optional[str], job_type: Optional[str]) -> str:
    parts = []
    if seniority:
        parts.append(config.SENIORITIES.get(seniority, seniority))
    parts.append(config.CATEGORIES.get(category, category) if category else "all software")
    parts.append("roles")
    if job_type:
        parts.append(f"({config.JOB_TYPES.get(job_type, job_type)})")
    return " ".join(parts)


def summary_key(category: Optional[str], seniority: Optional[str], job_type: Optional[str]) -> str:
    return f"{category or '*'}|{seniority or '*'}|{job_type or '*'}"
