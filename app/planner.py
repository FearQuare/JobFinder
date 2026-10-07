"""Profile ↔ market: gap analysis, job match scores and the AI learning plan.

Urgency is grounded in data first: each skill/language gets a score from how often
target postings ask for it, how often it is *required*, and how big the user's gap
is. The AI then orders the work into phases, explains it and picks resources, and
may adjust a priority only with a stated reason.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from . import ai, config, db, learning_resources as lr, profile as prof, reports

PRIORITIES = ["high", "medium", "low"]
HIGH_THRESHOLD = 30.0
MEDIUM_THRESHOLD = 12.0
MIN_GROUP_JOBS = 5

PLAN_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS learning_plans (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    provider TEXT, model TEXT,
    profile TEXT NOT NULL,
    market TEXT NOT NULL,
    plan TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learning_progress (
    plan_id INTEGER NOT NULL REFERENCES learning_plans(id) ON DELETE CASCADE,
    item_id TEXT NOT NULL,
    status TEXT NOT NULL,              -- todo | doing | done
    updated_at TEXT NOT NULL,
    PRIMARY KEY (plan_id, item_id)
);
"""


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(PLAN_SCHEMA_SQL)


# ---------------------------------------------------------------- market

def _analysed_categories(conn: sqlite3.Connection, window: int, limit: int = 2) -> List[str]:
    where, params = reports._group_where(conn, None, None, None, window)
    rows = conn.execute(f"SELECT j.category, COUNT(*) n FROM jobs j WHERE {where} GROUP BY j.category ORDER BY n DESC LIMIT ?",
                        (*params, limit)).fetchall()
    return [r["category"] for r in rows]


def market_for_profile(conn: sqlite3.Connection, p: Dict[str, Any], window: int) -> Dict[str, Any]:
    """Aggregate what employers ask for across the user's target roles and levels."""
    categories = p.get("target_categories") or _analysed_categories(conn, window)
    seniorities = p.get("target_seniorities") or []
    groups = []
    for cat in categories:
        picked = []
        for sen in seniorities:
            st = reports.group_stats(conn, cat, sen, None, window, top_n=60)
            if st["job_count"]:
                picked.append((sen, st))
        if sum(st["job_count"] for _, st in picked) < MIN_GROUP_JOBS:
            # too few postings at the exact level(s): use all levels of this role for a stable signal
            st = reports.group_stats(conn, cat, None, None, window, top_n=60)
            picked = [(None, st)] if st["job_count"] else []
        for sen, st in picked:
            groups.append({"category": cat, "seniority": sen, "job_count": st["job_count"], "stats": st})

    total = sum(g["job_count"] for g in groups)
    skills: Dict[str, Dict[str, float]] = {}
    names: Dict[str, Counter] = defaultdict(Counter)
    lang_weight: Dict[str, float] = defaultdict(float)
    lang_levels: Dict[str, Counter] = defaultdict(Counter)
    years: List[float] = []
    for g in groups:
        n = g["job_count"]
        for s in g["stats"]["skills"]:
            k = s["skill"].lower()
            names[k][s["skill"]] += s["count"]
            cur = skills.setdefault(k, {"count": 0, "req": 0.0})
            cur["count"] += s["count"]
            cur["req"] += s["count"] * s["required_pct"] / 100
        for l in g["stats"]["languages"]:
            lang_weight[l["language"]] += l["count"]
            lang_levels[l["language"]].update(l["levels"])
        med = g["stats"]["experience"].get("median_years")
        if med is not None:
            years.extend([med] * n)
    skill_list = []
    for k, v in skills.items():
        skill_list.append({
            "skill": names[k].most_common(1)[0][0],
            "count": int(v["count"]),
            "pct": round(100 * v["count"] / total) if total else 0,
            "required_pct": round(100 * v["req"] / v["count"]) if v["count"] else 0,
        })
    skill_list.sort(key=lambda s: (-s["pct"], -s["required_pct"], s["skill"]))
    languages = []
    for lang, c in sorted(lang_weight.items(), key=lambda kv: -kv[1]):
        levels = {k: v for k, v in lang_levels[lang].items() if k != "Level not stated"}
        typical = max(levels, key=lambda k: (levels[k], prof.language_rank(k))) if levels else ""
        languages.append({"language": lang, "count": int(c), "pct": round(100 * c / total) if total else 0,
                          "typical_level": typical, "levels": dict(lang_levels[lang])})
    return {
        "groups": [{k: g[k] for k in ("category", "seniority", "job_count")} for g in groups],
        "cert_mentions": _cert_mentions(conn, [g["category"] for g in groups], window),
        "total_jobs": total,
        "skills": skill_list[:60],
        "languages": languages[:5],
        "median_years": sorted(years)[len(years) // 2] if years else None,
    }


def _cert_mentions(conn: sqlite3.Connection, categories: List[str], window: int) -> Dict[str, int]:
    """Certifications named in the analysed target postings: lowercase text -> number of postings."""
    out: Dict[str, int] = {}
    for cat in dict.fromkeys(categories):
        where, params = reports._group_where(conn, cat, None, None, window)
        for r in conn.execute(
            f"SELECT lower(s.skill) AS k, COUNT(DISTINCT s.job_id) AS n FROM job_skills s JOIN jobs j ON j.id=s.job_id "
            f"WHERE {where} AND s.skill_type='certification' GROUP BY lower(s.skill)", params):
            out[r["k"]] = out.get(r["k"], 0) + r["n"]
    return out


# ---------------------------------------------------------------- gaps

def _int(v: Any, default: int) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _priority(score: float) -> str:
    return "high" if score >= HIGH_THRESHOLD else "medium" if score >= MEDIUM_THRESHOLD else "low"


def gap_analysis(p: Dict[str, Any], market: Dict[str, Any]) -> Dict[str, Any]:
    levels = prof.skill_levels(p)
    lang_ranks = prof.language_ranks(p)
    skills = []
    weight_sum = covered = 0.0
    for s in market["skills"]:
        have = levels.get(s["skill"].lower(), 0)
        gap = 1.0 if have == 0 else 0.5 if have == 1 else 0.0
        score = s["pct"] * (0.6 + 0.4 * s["required_pct"] / 100) * gap
        status = "strong" if have >= 2 else "partial" if have == 1 else "missing"
        skills.append({**s, "have_level": have, "status": status, "urgency_score": round(score, 1),
                       "suggested_priority": _priority(score) if gap else None})
        if len(skills) <= 25:
            weight_sum += s["pct"]
            covered += s["pct"] * (1 - gap)
    languages = []
    for l in market["languages"]:
        need = prof.language_rank(l["typical_level"]) or 4  # assume B2 when postings don't say
        have = lang_ranks.get(l["language"].lower(), 0)
        gap = max(0.0, (need - have) / need)
        score = l["pct"] * gap * 1.2
        languages.append({**l, "need_rank": need, "have_level": next((x["level"] for x in p.get("languages", [])
                                                                      if x["language"].lower() == l["language"].lower()), ""),
                          "gap": round(gap, 2), "urgency_score": round(score, 1),
                          "suggested_priority": _priority(score) if gap > 0 else None})
    match = round(100 * covered / weight_sum) if weight_sum else None
    return {
        "skills": skills,
        "languages": languages,
        "match_score": match,
        "strengths": [s["skill"] for s in skills if s["status"] == "strong"][:12],
        "top_gaps": [s for s in sorted(skills, key=lambda s: -s["urgency_score"]) if s["suggested_priority"]][:25],
    }


# ---------------------------------------------------------------- job match (used on the jobs list)

def job_match_scores(conn: sqlite3.Connection, p: Dict[str, Any], job_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    if not job_ids or not prof.is_filled(p):
        return {}
    levels = prof.skill_levels(p)
    lang_ranks = prof.language_ranks(p)
    out: Dict[int, Dict[str, Any]] = {}
    marks = ",".join("?" * len(job_ids))
    skill_rows = conn.execute(f"SELECT job_id, skill, required FROM job_skills WHERE job_id IN ({marks})", job_ids).fetchall()
    lang_rows = conn.execute(f"SELECT job_id, language, level, required FROM job_languages WHERE job_id IN ({marks})", job_ids).fetchall()
    by_job: Dict[int, list] = defaultdict(list)
    for r in skill_rows:
        by_job[r["job_id"]].append(r)
    langs: Dict[int, list] = defaultdict(list)
    for r in lang_rows:
        langs[r["job_id"]].append(r)
    for jid in job_ids:
        rows = by_job.get(jid)
        if not rows:
            continue
        total = got = 0.0
        missing = []
        for r in rows:
            w = 2.0 if r["required"] else 1.0
            have = levels.get(r["skill"].lower(), 0)
            credit = 1.0 if have >= 2 else 0.5 if have == 1 else 0.0
            total += w
            got += w * credit
            if r["required"] and credit < 1:
                missing.append(r["skill"])
        score = 100 * got / total if total else 0
        lang_gap = None
        for l in langs.get(jid, []):
            if not l["required"]:
                continue
            need = prof.language_rank(reports._level_bucket(l["level"])) or 3
            if lang_ranks.get(l["language"].lower(), 0) < need:
                lvl = reports._level_bucket(l["level"])
                lang_gap = f"{l['language']} {lvl if lvl != 'Level not stated' else ''}".strip()
                score *= 0.6
                break
        out[jid] = {"score": round(score), "missing": missing[:5], "language_gap": lang_gap}
    return out


# ---------------------------------------------------------------- AI plan

ITEM_KINDS = ["skill", "language", "certification", "project", "soft_skill"]
RESOURCE_TYPES = ["course", "docs", "book", "practice", "certification", "community", "roadmap"]

PLAN_TOOL_NAME = "record_learning_plan"
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "3-5 sentences: where the person stands against the target market and the main thing to fix first."},
        "strengths": {"type": "array", "items": {"type": "string"}, "description": "Existing strengths that employers in the data value (max 6)."},
        "phases": {"type": "array", "description": "3-5 sequential phases.", "items": {"type": "object", "properties": {
            "title": {"type": "string"}, "goal": {"type": "string", "description": "What the person can do / show at the end of the phase."}},
            "required": ["title", "goal"]}},
        "items": {"type": "array", "description": "8-18 learning items.", "items": {"type": "object", "properties": {
            "topic": {"type": "string", "description": "Imperative, e.g. 'Learn German to B1', 'Learn Kubernetes basics'."},
            "skill_key": {"type": "string", "description": "Exact skill or language name from the gap data this addresses, or '' if none."},
            "kind": {"type": "string", "enum": ITEM_KINDS},
            "priority": {"type": "string", "enum": PRIORITIES},
            "priority_reason": {"type": "string", "description": "One sentence citing the data (e.g. 'required in 72% of junior DevOps postings')."},
            "phase": {"type": "integer", "description": "1-based index into phases."},
            "order": {"type": "integer", "description": "Global learning order, 1 = first."},
            "current_level": {"type": "string"}, "target_level": {"type": "string"},
            "estimated_hours": {"type": "integer", "description": "Realistic hours to reach the target level."},
            "how": {"type": "string", "description": "2-3 sentences: what exactly to study and how, building on what the person already knows."},
            "practice_project": {"type": "string", "description": "A small portfolio project/exercise that proves the skill, or ''."},
            "resources": {"type": "array", "items": {"type": "object", "properties": {
                "title": {"type": "string"}, "url": {"type": "string", "description": "Use URLs from the provided catalog. Otherwise ''."},
                "type": {"type": "string", "enum": RESOURCE_TYPES}, "free": {"type": "boolean"}},
                "required": ["title", "url", "type", "free"]}}},
            "required": ["topic", "skill_key", "kind", "priority", "priority_reason", "phase", "order", "current_level",
                         "target_level", "estimated_hours", "how", "practice_project", "resources"]}},
        "job_search_tips": {"type": "array", "items": {"type": "string"}, "description": "3-5 concrete tips for this person's job search in Austria."},
    },
    "required": ["summary", "strengths", "phases", "items", "job_search_tips"],
}

PLAN_SYSTEM = """You are a pragmatic career coach for software/IT jobs in Austria. You build a personal learning roadmap
from REAL job-market data (skill frequencies from currently open postings) and the person's profile.

Rules:
- Priorities: start from each gap's "suggested_priority" (computed from how often postings require it and the size of the gap).
  Keep it unless you have a concrete reason; if you change it, say why in priority_reason. Every priority_reason must cite the data.
- High = blocks most applications now; Medium = asked for often, learn after the highs; Low = nice-to-have or rarely asked.
- Order items so foundations come first (e.g. Linux and Git before Docker, Docker before Kubernetes) and high-priority items
  appear early. Languages like German can run in parallel from phase 1.
- Build on existing skills (e.g. a C#/.NET developer learns cloud via Azure faster). Don't teach things the person already knows well.
- Estimated hours must be realistic for the person's current level; fit the plan to their weekly hours and timeline.
- Include at least one portfolio project that combines several high-priority skills.
- Resources: prefer the provided catalog URLs (verified). You may name other well-known resources, but leave url "" unless it is in the catalog.
- Roadmaps: from ROADMAP OPTIONS pick the 3-6 most useful for THIS person (mix of a role roadmap, a hands-on curriculum and,
  if useful, a portfolio challenge or interview-prep resource) and say how to use each alongside the plan.
- Certifications: from CERTIFICATION OPTIONS recommend the 2-5 that would make this candidate stand out for the target roles in
  Austria. Prefer certifications named in the postings (see "mentioned_in_postings"), go from foundational to advanced, respect
  prerequisites, and weigh cost against benefit (a cheap foundational cert early can open doors; expensive expert certs belong
  late, only if realistic). If German is a gap, include an ÖSD or Goethe certificate at the level employers ask for — Austrian
  employers often want proof of the level. Place each certification in the phase where the person will be ready for it.
- Write in English, concise and specific."""


def _profile_for_prompt(p: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "headline": p.get("headline"), "summary": p.get("summary"), "location": p.get("location"),
        "targets": {"roles": [config.CATEGORIES.get(c, c) for c in p.get("target_categories", [])],
                    "levels": [config.SENIORITIES.get(s, s) for s in p.get("target_seniorities", [])],
                    "contract_types": [config.JOB_TYPES.get(t, t) for t in p.get("target_job_types", [])],
                    "locations": p.get("preferred_locations")},
        "learning_time": {"hours_per_week": p.get("weekly_hours"), "wants_job_within_months": p.get("timeline_months")},
        "skills": [{"name": s["name"], "level": prof.SKILL_LEVELS.get(s["level"]), "years": s.get("years")} for s in p.get("skills", [])],
        "languages": p.get("languages"),
        "education": [{k: e[k] for k in ("degree", "field", "institution", "end", "status")} for e in p.get("education", [])],
        "experience": [{"title": e["title"], "company": e["company"], "start": e["start"], "end": e["end"] or ("now" if e["current"] else ""),
                        "technologies": e["technologies"], "description": e["description"][:400]} for e in p.get("experience", [])],
        "certifications": p.get("certifications"),
        "projects": [{"name": x["name"], "technologies": x["technologies"]} for x in p.get("projects", [])],
    }


def plan_options(p: Dict[str, Any], market: Dict[str, Any], gaps: Dict[str, Any]) -> Dict[str, List[dict]]:
    """The roadmaps and certifications the AI may choose from (all from the verified catalogs)."""
    cats = market_categories(market, p)
    gap_skills = [g["skill"] for g in gaps["top_gaps"]] + [s["name"] for s in p.get("skills", [])]
    lang_gaps = [l["language"] for l in gaps["languages"] if l.get("suggested_priority")]
    have_certs = " ".join(c["name"].lower() for c in p.get("certifications", []))
    certs = []
    for c in lr.certification_candidates(cats, gap_skills, lang_gaps):
        if any(a in have_certs for a in [c["name"].lower()] + c.get("aliases", [])):
            continue  # already has it
        certs.append({**c, "mentions": lr.cert_mentions(c, market.get("cert_mentions", {}))})
    return {"roadmaps": lr.roadmap_catalog(cats, p.get("target_seniorities", [])), "certs": certs}


def plan_schema(options: Dict[str, List[dict]]) -> Dict[str, Any]:
    """PLAN_SCHEMA plus roadmap/certification choices restricted (enum) to the catalog ids."""
    schema = json.loads(json.dumps(PLAN_SCHEMA))
    road_ids = [r["id"] for r in options["roadmaps"]] or ["none"]
    cert_ids = [c["id"] for c in options["certs"]] or ["none"]
    schema["properties"]["recommended_roadmaps"] = {"type": "array", "description": "3-6 picks from ROADMAP OPTIONS.", "items": {
        "type": "object", "properties": {
            "roadmap_id": {"type": "string", "enum": road_ids},
            "how_to_use": {"type": "string", "description": "One sentence: how this person should use it alongside the plan."}},
        "required": ["roadmap_id", "how_to_use"]}}
    schema["properties"]["certifications"] = {"type": "array", "description": "2-5 picks from CERTIFICATION OPTIONS.", "items": {
        "type": "object", "properties": {
            "cert_id": {"type": "string", "enum": cert_ids},
            "priority": {"type": "string", "enum": PRIORITIES},
            "phase": {"type": "integer", "description": "Phase in which the person should take the exam."},
            "why": {"type": "string", "description": "Why it makes this candidate stand out, citing the data where possible."},
            "prep_hours": {"type": "integer", "description": "Realistic preparation hours given the person's current level."}},
        "required": ["cert_id", "priority", "phase", "why", "prep_hours"]}}
    schema["required"] = schema["required"] + ["recommended_roadmaps", "certifications"]
    return schema


def build_plan_prompt(p: Dict[str, Any], market: Dict[str, Any], gaps: Dict[str, Any],
                      options: Optional[Dict[str, List[dict]]] = None) -> str:
    options = options or plan_options(p, market, gaps)
    target_desc = ", ".join(
        f"{config.CATEGORIES.get(g['category'], g['category'])} ({config.SENIORITIES.get(g['seniority'], 'all levels')}): {g['job_count']} postings"
        for g in market["groups"]) or "no analysed postings yet"
    gap_rows = [{"skill": g["skill"], "in_pct_of_postings": g["pct"], "required_in_pct": g["required_pct"],
                 "person_level": prof.SKILL_LEVELS.get(g["have_level"], "none"), "urgency_score": g["urgency_score"],
                 "suggested_priority": g["suggested_priority"]} for g in gaps["top_gaps"]]
    lang_rows = [{"language": l["language"], "in_pct_of_postings": l["pct"], "typical_level": l["typical_level"] or "not stated",
                  "person_level": l["have_level"] or "none", "suggested_priority": l["suggested_priority"]} for l in gaps["languages"]]
    catalog_keys = [g["skill"] for g in gaps["top_gaps"]] + [l["language"] for l in gaps["languages"]] + ["German", "Linux", "Git"]
    return "\n\n".join([
        f"TODAY: {date.today().isoformat()}",
        "PERSON'S PROFILE:\n" + json.dumps(_profile_for_prompt(p), ensure_ascii=False, indent=1),
        f"TARGET MARKET (currently open postings in Austria): {target_desc}. Median years of experience asked: {market.get('median_years')}.",
        "MOST REQUESTED SKILLS (top 30, % of target postings):\n" + json.dumps(
            [{"skill": s["skill"], "pct": s["pct"], "required_pct": s["required_pct"]} for s in market["skills"][:30]], ensure_ascii=False),
        "PERSON'S STRENGTHS ALREADY MATCHING DEMAND: " + (", ".join(gaps["strengths"]) or "none"),
        "SKILL GAPS WITH COMPUTED URGENCY:\n" + json.dumps(gap_rows, ensure_ascii=False, indent=1),
        "LANGUAGE REQUIREMENTS VS PERSON:\n" + json.dumps(lang_rows, ensure_ascii=False, indent=1),
        "RESOURCE CATALOG (verified URLs, use these):\n" + json.dumps(lr.catalog_for_prompt(catalog_keys), ensure_ascii=False),
        "ROADMAP OPTIONS (choose by roadmap_id):\n" + json.dumps(
            [{"roadmap_id": r["id"], "title": r["title"], "provider": r["provider"], "kind": r["kind"], "about": r["note"]}
             for r in options["roadmaps"]], ensure_ascii=False, indent=1),
        "CERTIFICATION OPTIONS (choose by cert_id; exam fee in USD, null = see issuer site):\n" + json.dumps(
            [{"cert_id": c["id"], "name": c["name"], "issuer": c["issuer"], "level": c["level"], "exam_fee_usd": c.get("cost"),
              "prerequisite": c.get("prereq"), "mentioned_in_postings": c["mentions"]} for c in options["certs"]],
            ensure_ascii=False, indent=1),
    ])


def market_categories(market: Dict[str, Any], p: Dict[str, Any]) -> List[str]:
    cats = p.get("target_categories") or []
    for g in market["groups"]:
        if g["category"] not in cats:
            cats = cats + [g["category"]]
    return cats


def postprocess_plan(raw: Dict[str, Any], p: Dict[str, Any], market: Dict[str, Any], gaps: Dict[str, Any],
                     options: Optional[Dict[str, List[dict]]] = None) -> Dict[str, Any]:
    options = options or plan_options(p, market, gaps)
    evidence = {g["skill"].lower(): g for g in gaps["skills"]}
    lang_evidence = {l["language"].lower(): l for l in gaps["languages"]}
    phases = [{"title": str(ph.get("title") or f"Phase {i + 1}")[:120], "goal": str(ph.get("goal") or "")[:400]}
              for i, ph in enumerate(raw.get("phases") or [])] or [{"title": "Plan", "goal": ""}]
    items = []
    for i, it in enumerate(raw.get("items") or []):
        if not isinstance(it, dict) or not it.get("topic"):
            continue
        key = ai.canonical_skill(str(it.get("skill_key") or ""))
        ev = evidence.get(key.lower())
        lev = lang_evidence.get(key.lower())
        market_note = None
        if ev:
            market_note = {"pct": ev["pct"], "required_pct": ev["required_pct"], "suggested": ev["suggested_priority"]}
        elif lev:
            market_note = {"pct": lev["pct"], "typical_level": lev["typical_level"], "suggested": lev["suggested_priority"]}
        resources, seen = [], set()
        for res in lr.resources_for(key) + [lr.safe_resource(r, str(it["topic"])) for r in (it.get("resources") or []) if isinstance(r, dict)]:
            res = {**res, "verified": res.get("verified", True)}
            if res["url"] in seen:
                continue
            seen.add(res["url"])
            resources.append({k: res.get(k) for k in ("title", "url", "type", "free", "verified")})
        rm = lr.roadmap_for_skill(key)
        phase = max(1, min(len(phases), _int(it.get("phase"), 1)))
        items.append({
            "id": f"i{i + 1}",
            "topic": str(it["topic"])[:160],
            "skill_key": key,
            "kind": it.get("kind") if it.get("kind") in ITEM_KINDS else "skill",
            "priority": it.get("priority") if it.get("priority") in PRIORITIES else (market_note or {}).get("suggested") or "medium",
            "priority_reason": str(it.get("priority_reason") or "")[:400],
            "phase": phase,
            "order": _int(it.get("order"), i + 1),
            "current_level": str(it.get("current_level") or "")[:60],
            "target_level": str(it.get("target_level") or "")[:60],
            "estimated_hours": max(1, min(600, _int(it.get("estimated_hours"), 10))),
            "how": str(it.get("how") or "")[:800],
            "practice_project": str(it.get("practice_project") or "")[:600],
            "resources": resources[:5],
            "roadmap": rm,
            "market": market_note,
        })
    items.sort(key=lambda x: (x["phase"], x["order"]))
    for n, it in enumerate(items, 1):
        it["order"] = n
    # Timeline from the person's weekly hours (languages run in parallel, so they don't extend phases).
    weekly = max(1, int(p.get("weekly_hours") or 10))
    start = date.today()
    for idx, ph in enumerate(phases, 1):
        hours = sum(it["estimated_hours"] for it in items if it["phase"] == idx and it["kind"] != "language")
        weeks = max(1, -(-hours // weekly))
        ph.update(index=idx, hours=hours, weeks=weeks, start=start.isoformat(), end=(start + timedelta(weeks=weeks)).isoformat())
        start += timedelta(weeks=weeks)
    total_hours = sum(it["estimated_hours"] for it in items)

    roadmaps_by_id = {r["id"]: r for r in options["roadmaps"]}
    picked_roadmaps, seen_r = [], set()
    for r in raw.get("recommended_roadmaps") or []:
        rid = (r or {}).get("roadmap_id")
        if rid in roadmaps_by_id and rid not in seen_r:
            seen_r.add(rid)
            picked_roadmaps.append({**roadmaps_by_id[rid], "how_to_use": str(r.get("how_to_use") or "")[:300]})
    other_roadmaps = [r for r in options["roadmaps"] if r["id"] not in seen_r]

    certs_by_id = {c["id"]: c for c in options["certs"]}
    certs, seen_c = [], set()
    for c in raw.get("certifications") or []:
        cid = (c or {}).get("cert_id")
        if cid not in certs_by_id or cid in seen_c:
            continue
        seen_c.add(cid)
        cat = certs_by_id[cid]
        certs.append({
            "id": cid, "name": cat["name"], "issuer": cat["issuer"], "level": cat["level"], "url": cat["url"],
            "cost": cat.get("cost"), "prereq": cat.get("prereq"), "note": cat.get("note"), "mentions": cat["mentions"],
            "priority": c.get("priority") if c.get("priority") in PRIORITIES else "medium",
            "phase": max(1, min(len(phases), _int(c.get("phase"), len(phases)))),
            "why": str(c.get("why") or "")[:500],
            "prep_hours": max(1, min(400, _int(c.get("prep_hours"), 30))),
        })
    certs.sort(key=lambda c: (PRIORITIES.index(c["priority"]), c["phase"], lr.LEVEL_ORDER.get(c["level"], 9)))
    for ph in phases:
        ph["certifications"] = [c["name"] for c in certs if c["phase"] == ph["index"]]

    return {
        "summary": str(raw.get("summary") or ""),
        "strengths": [str(s) for s in (raw.get("strengths") or [])][:8],
        "phases": phases,
        "items": items,
        "job_search_tips": [str(t) for t in (raw.get("job_search_tips") or [])][:6],
        "match_score": gaps["match_score"],
        "total_hours": total_hours,
        "total_weeks": sum(ph["weeks"] for ph in phases),
        "weekly_hours": weekly,
        "role_roadmaps": lr.role_roadmaps(market_categories(market, p), p.get("target_seniorities", [])),
        "recommended_roadmaps": picked_roadmaps,
        "other_roadmaps": other_roadmaps,
        "certifications": certs,
        "total_market_postings_with_certs": sum(market.get("cert_mentions", {}).values()),
        "market": {"groups": market["groups"], "total_jobs": market["total_jobs"]},
        "counts": {pr: sum(1 for it in items if it["priority"] == pr) for pr in PRIORITIES},
    }


async def generate_plan(conn: sqlite3.Connection, analyzer: "ai.BaseAnalyzer", p: Dict[str, Any], window: int) -> int:
    ensure_tables(conn)
    market = market_for_profile(conn, p, window)
    gaps = gap_analysis(p, market)
    options = plan_options(p, market, gaps)
    raw = await analyzer.structured(PLAN_TOOL_NAME, "Record the personal learning plan as JSON.", plan_schema(options), PLAN_SYSTEM,
                                    build_plan_prompt(p, market, gaps, options), max_tokens=32000)
    plan = postprocess_plan(raw, p, market, gaps, options)
    plan["generated_with"] = {"provider": analyzer.provider, "model": analyzer.model,
                              "effort": getattr(analyzer, "effort", None) or getattr(analyzer, "REASONING_EFFORT", None)}
    cur = conn.execute(
        "INSERT INTO learning_plans(created_at, provider, model, profile, market, plan) VALUES (?,?,?,?,?,?)",
        (db.now_iso(), analyzer.provider, analyzer.model, json.dumps(p), json.dumps({"market": market, "gaps": gaps}), json.dumps(plan)),
    )
    return cur.lastrowid


def load_plan(conn: sqlite3.Connection, plan_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    ensure_tables(conn)
    row = conn.execute(
        "SELECT * FROM learning_plans WHERE id=?" if plan_id else "SELECT * FROM learning_plans ORDER BY id DESC LIMIT 1",
        (plan_id,) if plan_id else (),
    ).fetchone()
    if not row:
        return None
    plan = json.loads(row["plan"])
    progress = {r["item_id"]: r["status"] for r in conn.execute("SELECT item_id, status FROM learning_progress WHERE plan_id=?", (row["id"],))}
    for it in plan["items"]:
        it["status"] = progress.get(it["id"], "todo")
    done_hours = sum(it["estimated_hours"] for it in plan["items"] if it["status"] == "done")
    plan["progress_pct"] = round(100 * done_hours / plan["total_hours"]) if plan.get("total_hours") else 0
    extra = json.loads(row["market"])
    return {"id": row["id"], "created_at": row["created_at"], "provider": row["provider"], "model": row["model"],
            "plan": plan, "gaps": extra.get("gaps"), "market": extra.get("market")}


def list_plans(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    ensure_tables(conn)
    return [dict(r) for r in conn.execute("SELECT id, created_at, model FROM learning_plans ORDER BY id DESC LIMIT 20")]


def set_progress(conn: sqlite3.Connection, plan_id: int, item_id: str, status: str) -> None:
    if status not in ("todo", "doing", "done"):
        raise ValueError("bad status")
    ensure_tables(conn)
    conn.execute(
        "INSERT INTO learning_progress(plan_id, item_id, status, updated_at) VALUES (?,?,?,?) "
        "ON CONFLICT(plan_id, item_id) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at",
        (plan_id, item_id, status, db.now_iso()),
    )
