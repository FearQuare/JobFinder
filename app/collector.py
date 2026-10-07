"""Background runs: collecting jobs from the sources, and AI analysis.

Runs happen in a background thread with their own asyncio loop, so the web UI
stays responsive and can poll progress.
"""
from __future__ import annotations

import asyncio
import json
import threading
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional

from . import ai, config, db, repo, secrets_store
from .sources.adzuna import AdzunaSource
from .sources.base import AuthRequired, Blocked, JobSource, RawJob, SourceError
from .sources.karriere import KarriereSource
from .sources.linkedin import LinkedInSource


class RunState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self.data: Dict[str, Any] = {"status": "idle"}

    def reset(self, kind: str, run_id: int) -> None:
        with self.lock:
            self.cancel.clear()
            self.data = {
                "status": "running", "kind": kind, "run_id": run_id, "phase": "starting",
                "started_at": db.now_iso(), "finished_at": None, "message": "",
                "counters": {"pages": 0, "seen": 0, "new_jobs": 0, "details_done": 0, "details_total": 0,
                             "analysed": 0, "analyse_total": 0, "errors": 0},
                "sources": {}, "log": [],
            }

    def log(self, msg: str, error: bool = False) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        with self.lock:
            self.data.setdefault("log", []).append(f"{stamp}  {'⚠ ' if error else ''}{msg}")
            self.data["log"] = self.data["log"][-300:]
            if error:
                self.data["counters"]["errors"] += 1

    def update(self, **kwargs) -> None:
        with self.lock:
            self.data.update(kwargs)

    def bump(self, key: str, n: int = 1) -> None:
        with self.lock:
            self.data["counters"][key] = self.data["counters"].get(key, 0) + n

    def set_source(self, source: str, status: str) -> None:
        with self.lock:
            self.data.setdefault("sources", {})[source] = status

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return json.loads(json.dumps(self.data))

    @property
    def running(self) -> bool:
        with self.lock:
            return self.data.get("status") == "running"


STATE = RunState()


# ---------------------------------------------------------------- public API

def start_collect(search_ids: Optional[List[int]] = None) -> Dict[str, Any]:
    return _start("collect", lambda run_id: _collect(run_id, search_ids))


def start_analyze() -> Dict[str, Any]:
    return _start("analyze", _analyze_only)


def cancel() -> None:
    STATE.cancel.set()
    STATE.log("Stopping… (finishing the current request)")


def _start(kind: str, coro_factory) -> Dict[str, Any]:
    if STATE.running:
        raise RuntimeError("Another run is already in progress.")
    with db.session() as conn:
        run_id = conn.execute("INSERT INTO runs(kind, started_at, status) VALUES (?,?, 'running')", (kind, db.now_iso())).lastrowid
    STATE.reset(kind, run_id)

    def worker():
        status = "done"
        try:
            asyncio.run(coro_factory(run_id))
            if STATE.cancel.is_set():
                status = "cancelled"
        except Exception as exc:  # keep the app alive whatever happens
            status = "failed"
            STATE.log(f"Run failed: {exc}", error=True)
            traceback.print_exc()
        snap = STATE.snapshot()
        STATE.update(status=status, finished_at=db.now_iso(), phase="finished")
        with db.session() as conn:
            conn.execute(
                "UPDATE runs SET status=?, finished_at=?, stats=?, log=? WHERE id=?",
                (status, db.now_iso(), json.dumps(snap.get("counters")), "\n".join(snap.get("log", [])), run_id),
            )

    threading.Thread(target=worker, name=f"jobfinder-{kind}", daemon=True).start()
    return STATE.snapshot()


# ---------------------------------------------------------------- collection

def _build_sources(settings: Dict[str, str], wanted: set) -> Dict[str, JobSource]:
    sources: Dict[str, JobSource] = {}
    if "karriere" in wanted:
        sources["karriere"] = KarriereSource()
    if "linkedin" in wanted:
        sources["linkedin"] = LinkedInSource(
            mode=settings.get("linkedin_mode", "public"),
            posted_within_days=db.int_setting(settings, "linkedin_posted_within_days"),
            show_browser=settings.get("linkedin_show_browser") == "1",
        )
    if "adzuna" in wanted:
        try:
            sources["adzuna"] = AdzunaSource(secrets_store.get_secret("adzuna_app_id"), secrets_store.get_secret("adzuna_app_key"))
        except AuthRequired as exc:
            STATE.log(f"Adzuna skipped: {exc}")
            STATE.set_source("adzuna", "skipped (no API key)")
    return sources


async def _collect(run_id: int, search_ids: Optional[List[int]]) -> None:
    conn = db.connect()
    try:
        settings = db.get_settings(conn)
        rows = conn.execute("SELECT * FROM searches WHERE enabled=1 ORDER BY id").fetchall()
        searches = [r for r in rows if not search_ids or r["id"] in search_ids]
        if not searches:
            STATE.log("No enabled searches. Add or enable one on the Searches page.", error=True)
            return
        wanted = set()
        for s in searches:
            wanted.update(json.loads(s["sources"]))
        sources = _build_sources(settings, wanted)
        max_pages = {
            "karriere": db.int_setting(settings, "karriere_max_pages"),
            "linkedin": db.int_setting(settings, "linkedin_max_pages"),
            "adzuna": db.int_setting(settings, "adzuna_max_pages"),
        }
        STATE.update(phase="collecting")
        STATE.log(f"Collecting for {len(searches)} search(es) from: {', '.join(config.SOURCES[k] for k in sources)}")
        try:
            await asyncio.gather(*[
                _collect_source(conn, src, [s for s in searches if key in json.loads(s["sources"])], max_pages[key])
                for key, src in sources.items()
            ])
        finally:
            for src in sources.values():
                await src.aclose()
        c = STATE.snapshot()["counters"]
        STATE.log(f"Collection finished: {c['seen']} listings seen, {c['new_jobs']} new jobs.")

        if STATE.cancel.is_set():
            return
        if settings.get("ai_auto_analyze") == "1":
            if ai.has_key(settings):
                await _analyze(conn, settings)
            else:
                provider = ai.PROVIDERS[ai.current_provider(settings)]
                STATE.log(f"AI analysis skipped: add your {provider} API key in Settings to get skill reports.")
    finally:
        conn.close()


async def _collect_source(conn, source: JobSource, searches, max_pages: int) -> None:
    key = source.key
    label = config.SOURCES[key]
    STATE.set_source(key, "searching")
    detail_queue: Dict[str, RawJob] = {}
    try:
        for search in searches:
            for keyword in json.loads(search["keywords"]):
                if STATE.cancel.is_set():
                    return
                count = 0
                try:
                    async for page in source.search(keyword, max_pages):
                        if STATE.cancel.is_set():
                            return
                        STATE.bump("pages")
                        for raw in page:
                            count += 1
                            await _store_listing(conn, source, raw, search["id"], detail_queue)
                        conn.commit()
                except (AuthRequired, Blocked):
                    raise
                except SourceError as exc:
                    STATE.log(f"{label}: '{keyword}' failed: {exc}", error=True)
                    continue
                STATE.log(f"{label}: '{keyword}' → {count} listings")

        if detail_queue:
            STATE.set_source(key, "fetching descriptions")
            STATE.bump("details_total", len(detail_queue))
            STATE.log(f"{label}: fetching {len(detail_queue)} job descriptions…")
            failures = 0
            for raw in detail_queue.values():
                if STATE.cancel.is_set():
                    return
                try:
                    full = await source.fetch_detail(raw)
                    repo.apply_detail(conn, full)
                    conn.commit()
                except (AuthRequired, Blocked):
                    raise
                except SourceError as exc:
                    failures += 1
                    if failures <= 5:
                        STATE.log(f"{label}: description for '{raw.title or raw.source_id}' failed: {exc}", error=True)
                STATE.bump("details_done")
        STATE.set_source(key, "done")
    except (AuthRequired, Blocked) as exc:
        STATE.log(f"{label} stopped: {exc}", error=True)
        STATE.set_source(key, "stopped")
        conn.commit()


async def _store_listing(conn, source: JobSource, raw: RawJob, search_id: int, detail_queue: Dict[str, RawJob]) -> None:
    STATE.bump("seen")
    if not raw.title and not repo.known_listing(conn, raw.source, raw.source_id):
        # Logged-in LinkedIn results only carry an ID; fetch the posting first to know what it is.
        try:
            raw = await source.fetch_detail(raw)
        except SourceError as exc:
            STATE.log(f"{config.SOURCES[source.key]}: job {raw.source_id} skipped: {exc}", error=True)
            return
        if not raw.title:
            return
        job_id, is_new, _ = repo.upsert_listing(conn, raw, search_id, source.supports_detail)
        repo.apply_detail(conn, raw)
    else:
        job_id, is_new, needs_detail = repo.upsert_listing(conn, raw, search_id, source.supports_detail)
        if needs_detail:
            detail_queue.setdefault(raw.source_id, raw)
    if is_new:
        STATE.bump("new_jobs")


# ---------------------------------------------------------------- AI analysis

async def _analyze_only(run_id: int) -> None:
    conn = db.connect()
    try:
        settings = db.get_settings(conn)
        if not ai.has_key(settings):
            STATE.log(f"Add your {ai.PROVIDERS[ai.current_provider(settings)]} API key in Settings first.", error=True)
            return
        await _analyze(conn, settings)
    finally:
        conn.close()


async def _analyze(conn, settings: Dict[str, str]) -> None:
    window = db.int_setting(settings, "active_window_days")
    cutoff = repo.active_cutoff(conn, window) or "0000"
    jobs = conn.execute(
        """SELECT id, title, company, location, employment_raw, description FROM jobs
           WHERE ai_status IN ('pending','error') AND closed=0 AND last_seen_at >= ?
           ORDER BY first_seen_at DESC""",
        (cutoff,),
    ).fetchall()
    if not jobs:
        STATE.log("AI analysis: nothing new to analyse.")
        return
    analyzer = ai.make_analyzer(settings)
    model = analyzer.model
    STATE.update(phase="analysing")
    STATE.bump("analyse_total", len(jobs))
    STATE.log(f"AI analysis of {len(jobs)} jobs with {ai.PROVIDERS[analyzer.provider]} · {model}…")
    abort: Dict[str, Optional[str]] = {"reason": None}
    error_count = {"n": 0}

    async def one(job) -> None:
        if STATE.cancel.is_set() or abort["reason"]:
            return
        try:
            result = await analyzer.analyse_job(dict(job))
            repo.save_ai_result(conn, job["id"], result, model)
            conn.commit()
            STATE.bump("analysed")
        except ai.AIAuthError as exc:
            if not abort["reason"]:
                abort["reason"] = str(exc)
        except ai.AIError as exc:
            repo.save_ai_error(conn, job["id"], str(exc))
            conn.commit()
            error_count["n"] += 1
            if error_count["n"] <= 5:
                STATE.log(f"AI: '{job['title']}' failed: {exc}", error=True)

    try:
        await asyncio.gather(*[one(j) for j in jobs])
    finally:
        await analyzer.aclose()
    if abort["reason"]:
        STATE.log(f"AI analysis stopped: {abort['reason']}", error=True)
    else:
        STATE.log(f"AI analysis finished: {STATE.snapshot()['counters']['analysed']} jobs analysed.")


def last_runs(limit: int = 10) -> List[dict]:
    with db.session() as conn:
        rows = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
