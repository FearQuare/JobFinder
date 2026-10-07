"""FastAPI web app: pages + small JSON API for background runs."""
from __future__ import annotations

import json
import math
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlencode

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__, ai, collector, config, db, planner, reports, repo, secrets_store, security
from . import profile as prof
from .sources import linkedin_session

HERE = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_app):
    db.init_db()
    yield


app = FastAPI(title="JobFinder", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.middleware("http")(security.guard)
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
templates = Jinja2Templates(directory=str(HERE / "templates"))
templates.env.globals.update(
    CATEGORIES=config.CATEGORIES, SENIORITIES=config.SENIORITIES, JOB_TYPES=config.JOB_TYPES, SOURCES=config.SOURCES, AI_PROVIDERS=ai.PROVIDERS,
    version=__version__,
)


def _pct_bar(pct) -> str:
    return f"{max(0, min(100, int(pct or 0)))}%"


templates.env.filters["bar"] = _pct_bar
templates.env.filters["markdown"] = security.render_markdown
templates.env.filters["safe_url"] = security.safe_url
templates.env.filters["num"] = lambda n: f"{int(n or 0):,}"


def _humanize(value) -> str:
    """'vocational_or_htl' -> 'Vocational or HTL' (Jinja's capitalize would lowercase the rest)."""
    text = str(value or "").replace("_", " ").replace(" htl", " HTL")
    return text[:1].upper() + text[1:]


templates.env.filters["humanize"] = _humanize
templates.env.filters["fromjson"] = lambda text: json.loads(text) if text else {}


def _render(request: Request, name: str, **ctx) -> HTMLResponse:
    ctx.setdefault("active_page", name.split(".")[0])
    return templates.TemplateResponse(request, name, ctx)


def _clean_filters(request: Request) -> dict:
    keys = ("q", "search_id", "category", "seniority", "job_type", "source", "skill", "location", "posted_days", "sort", "status", "hide_other")
    f = {k: request.query_params.get(k, "").strip() for k in keys}
    # Hand-edited or stale links shouldn't crash the page: drop values that aren't valid choices.
    for key in ("search_id", "posted_days"):
        if not f[key].isdigit():
            f[key] = ""
    for key, allowed in (("category", config.CATEGORIES), ("seniority", config.SENIORITIES), ("job_type", config.JOB_TYPES),
                         ("source", config.SOURCES)):
        if f[key] not in allowed:
            f[key] = ""
    if f["sort"] not in ("posted", "found", "company", "match"):
        f["sort"] = ""
    f["status"] = f["status"] if f["status"] in ("open", "all") else "open"
    f["hide_other"] = f["hide_other"] != "0"
    return f


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    """JSON for the API, a normal page for everything a person opens in the browser."""
    if request.url.path.startswith("/api/") or "text/html" not in request.headers.get("accept", ""):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))
    return templates.TemplateResponse(request, "error.html", {"status": exc.status_code, "detail": exc.detail, "active_page": ""},
                                      status_code=exc.status_code)


# ------------------------------------------------------------------ pages

@app.get("/", response_class=HTMLResponse)
def jobs_page(request: Request, page: int = 1):
    f = _clean_filters(request)
    page = max(1, page)
    with db.session() as conn:
        settings = db.get_settings(conn)
        window = db.int_setting(settings, "active_window_days")
        profile_data, _ = prof.load(conn)
        has_profile = prof.is_filled(profile_data)
        if f["sort"] == "match" and has_profile:
            ids = repo.list_job_ids(conn, f, window)
            scores = planner.job_match_scores(conn, profile_data, ids)
            ids.sort(key=lambda i: -(scores.get(i, {}).get("score", -1)))
            total = len(ids)
            rows = repo.jobs_by_ids(conn, ids[(page - 1) * 50: page * 50])
        else:
            if f["sort"] == "match":
                f["sort"] = "posted"
            rows, total = repo.list_jobs(conn, f, window, page=page)
            scores = planner.job_match_scores(conn, profile_data, [r["id"] for r in rows]) if has_profile else {}
        searches = conn.execute("SELECT id, name FROM searches ORDER BY id").fetchall()
        counts = repo.dashboard_counts(conn, window)
    jobs = []
    for r in rows:
        listings = []
        for line in (r["listing_info"] or "").split("\n"):
            if "|" in line:
                src, url = line.split("|", 1)
                listings.append({"source": src, "url": url})
        jobs.append({**dict(r), "listings": listings, "match": scores.get(r["id"])})
    pages = max(1, math.ceil(total / 50))
    base_q = {k: (v if not isinstance(v, bool) else ("1" if v else "0")) for k, v in f.items() if v not in ("", None)}
    return _render(
        request, "jobs.html", jobs=jobs, total=total, page=page, pages=pages, f=f, searches=searches, counts=counts,
        has_profile=has_profile,
        page_url=lambda p: "/?" + urlencode({**base_q, "page": p}),
        has_ai_key=ai.has_key(settings), ai_provider=ai.PROVIDERS[ai.current_provider(settings)],
    )


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: int):
    with db.session() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            raise HTTPException(404, "Job not found")
        listings = repo.job_listings(conn, job_id)
        skills = conn.execute("SELECT * FROM job_skills WHERE job_id=? ORDER BY required DESC, skill_type, skill", (job_id,)).fetchall()
        languages = conn.execute("SELECT * FROM job_languages WHERE job_id=?", (job_id,)).fetchall()
        searches = conn.execute(
            "SELECT s.name FROM searches s JOIN job_searches js ON js.search_id=s.id WHERE js.job_id=?", (job_id,)
        ).fetchall()
    ai_data = json.loads(job["ai_data"]) if job["ai_data"] else None
    return _render(request, "job.html", job=dict(job), listings=listings, skills=skills, languages=languages,
                   searches=searches, ai_data=ai_data, active_page="jobs")


@app.get("/insights", response_class=HTMLResponse)
def insights_page(request: Request, category: str = "", seniority: str = "", job_type: str = ""):
    with db.session() as conn:
        settings = db.get_settings(conn)
        window = db.int_setting(settings, "active_window_days")
        counts = repo.dashboard_counts(conn, window)
        group = None
        summary = None
        if category or seniority or job_type:
            group = reports.group_stats(conn, category or None, seniority or None, job_type or None, window)
            row = conn.execute("SELECT * FROM summaries WHERE key=?", (reports.summary_key(category, seniority, job_type),)).fetchone()
            summary = dict(row) if row else None
        overview = reports.overview(conn, window, job_type or None) if not (category or seniority) else []
    grouped: List[tuple] = []
    for row in overview:  # keep the configured category order
        if grouped and grouped[-1][0] == row["category"]:
            grouped[-1][1].append(row)
        else:
            grouped.append((row["category"], [row]))
    return _render(
        request, "insights.html", overview=grouped, group=group, summary=summary, counts=counts,
        sel={"category": category, "seniority": seniority, "job_type": job_type},
        title=reports.group_title(category or None, seniority or None, job_type or None),
        has_ai_key=ai.has_key(settings), ai_provider=ai.PROVIDERS[ai.current_provider(settings)],
    )


@app.post("/insights/summary")
async def insights_summary(category: str = Form(""), seniority: str = Form(""), job_type: str = Form("")):
    back = "/insights?" + urlencode({"category": category, "seniority": seniority, "job_type": job_type})
    with db.session() as conn:
        settings = db.get_settings(conn)
    if not ai.has_key(settings):
        return RedirectResponse(back + "&error=no_key", status_code=303)
    with db.session() as conn:
        window = db.int_setting(settings, "active_window_days")
        stats = reports.group_stats(conn, category or None, seniority or None, job_type or None, window, top_n=30)
    if stats["job_count"] == 0:
        return RedirectResponse(back, status_code=303)
    try:
        analyzer = ai.make_analyzer(settings, concurrency=1)
    except ai.AIError as exc:
        return RedirectResponse(back + "&" + urlencode({"error": str(exc)}), status_code=303)
    model = analyzer.model
    try:
        text = await analyzer.summarise_group(reports.group_title(category or None, seniority or None, job_type or None), stats)
    except ai.AIError as exc:
        return RedirectResponse(back + "&" + urlencode({"error": str(exc)}), status_code=303)
    finally:
        await analyzer.aclose()
    with db.session() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO summaries(key, job_count, content, model, created_at) VALUES (?,?,?,?,?)",
            (reports.summary_key(category, seniority, job_type), stats["job_count"], text, model, db.now_iso()),
        )
    return RedirectResponse(back, status_code=303)


@app.get("/searches", response_class=HTMLResponse)
def searches_page(request: Request):
    with db.session() as conn:
        rows = conn.execute(
            """SELECT s.*, (SELECT COUNT(*) FROM job_searches js WHERE js.search_id=s.id) AS job_count
               FROM searches s ORDER BY s.id"""
        ).fetchall()
    searches = [{**dict(r), "keywords": json.loads(r["keywords"]), "sources": json.loads(r["sources"])} for r in rows]
    return _render(request, "searches.html", searches=searches, runs=collector.last_runs(8))


def _parse_keywords(text: str) -> List[str]:
    parts = [p.strip() for line in text.splitlines() for p in line.split(",")]
    return list(dict.fromkeys(p for p in parts if p))


@app.post("/searches")
def create_search(name: str = Form(""), keywords: str = Form(""), sources: List[str] = Form(default=[])):
    kws = _parse_keywords(keywords)
    if not name.strip() or not kws:
        raise HTTPException(400, "Add a name and at least one keyword.")
    srcs = [s for s in sources if s in config.SOURCES] or list(config.SOURCES)
    with db.session() as conn:
        conn.execute("INSERT INTO searches(name, keywords, sources, enabled, created_at) VALUES (?,?,?,1,?)",
                     (name.strip(), json.dumps(kws), json.dumps(srcs), db.now_iso()))
    return RedirectResponse("/searches", status_code=303)


@app.post("/searches/{search_id}")
def update_search(search_id: int, name: str = Form(""), keywords: str = Form(""), sources: List[str] = Form(default=[]),
                  enabled: Optional[str] = Form(None)):
    kws = _parse_keywords(keywords)
    if not name.strip() or not kws:
        raise HTTPException(400, "Add a name and at least one keyword.")
    srcs = [s for s in sources if s in config.SOURCES]
    with db.session() as conn:
        conn.execute("UPDATE searches SET name=?, keywords=?, sources=?, enabled=? WHERE id=?",
                     (name.strip(), json.dumps(kws), json.dumps(srcs), 1 if enabled else 0, search_id))
    return RedirectResponse("/searches", status_code=303)


@app.post("/searches/{search_id}/delete")
def delete_search(search_id: int):
    with db.session() as conn:
        conn.execute("DELETE FROM searches WHERE id=?", (search_id,))
    return RedirectResponse("/searches", status_code=303)


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, saved: str = ""):
    with db.session() as conn:
        settings = db.get_settings(conn)
    keys = {k: secrets_store.mask(secrets_store.get_secret(k)) for k in secrets_store.KNOWN_KEYS}
    return _render(request, "settings.html", settings=settings, keys=keys, saved=saved,
                   planning_options=ai.planning_options(settings), efforts=ai.EFFORTS,
                   planning_current=(lambda c: f"{c['provider']}:{c['model']}" if c else "")(ai.planning_choice(settings)),
                   storage=secrets_store.storage_backend(), linkedin=linkedin_session.connection_info(),
                   playwright_missing=linkedin_session.playwright_available())


@app.post("/settings/keys")
def save_keys(anthropic_api_key: str = Form(""), openai_api_key: str = Form(""), adzuna_app_id: str = Form(""),
              adzuna_app_key: str = Form(""), clear: str = Form("")):
    if clear in secrets_store.KNOWN_KEYS:
        secrets_store.delete_secret(clear)
        return RedirectResponse("/settings?saved=removed", status_code=303)
    for name, value in (("anthropic_api_key", anthropic_api_key), ("openai_api_key", openai_api_key),
                        ("adzuna_app_id", adzuna_app_id), ("adzuna_app_key", adzuna_app_key)):
        if value.strip():
            secrets_store.set_secret(name, value)
    # If only one AI provider has a key, use that one.
    has_anthropic = bool(secrets_store.get_secret("anthropic_api_key"))
    has_openai = bool(secrets_store.get_secret("openai_api_key"))
    if has_anthropic != has_openai:
        with db.session() as conn:
            db.set_setting(conn, "ai_provider", "openai" if has_openai else "anthropic")
    return RedirectResponse("/settings?saved=keys", status_code=303)


_NUMERIC_SETTINGS = {
    "karriere_max_pages": (1, 100), "linkedin_max_pages": (1, 40), "adzuna_max_pages": (1, 20),
    "linkedin_posted_within_days": (0, 90), "active_window_days": (1, 90), "ai_concurrency": (1, 10),
}


@app.post("/settings/options")
async def save_options(request: Request):
    form = await request.form()
    with db.session() as conn:
        for key, (lo, hi) in _NUMERIC_SETTINGS.items():
            if key in form:
                try:
                    db.set_setting(conn, key, max(lo, min(hi, int(form[key]))))
                except ValueError:
                    pass
        if form.get("linkedin_mode") in ("public", "logged_in"):
            mode = form["linkedin_mode"]
            if mode == "logged_in" and not linkedin_session.is_connected():
                mode = "public"
            db.set_setting(conn, "linkedin_mode", mode)
        db.set_setting(conn, "linkedin_show_browser", "1" if form.get("linkedin_show_browser") else "0")
        db.set_setting(conn, "ai_auto_analyze", "1" if form.get("ai_auto_analyze") else "0")
        if form.get("ai_provider") in ai.PROVIDERS:
            db.set_setting(conn, "ai_provider", form["ai_provider"])
        for key in ("ai_model", "openai_model"):
            if form.get(key, "").strip():
                db.set_setting(conn, key, form[key].strip())
        planning = (form.get("planning_model") or "").strip()
        if planning == "custom":
            prov, custom = form.get("planning_custom_provider"), (form.get("planning_custom_model") or "").strip()
            if prov in ai.PROVIDERS and custom:
                db.set_setting(conn, "planning_model", f"{prov}:{custom}")
        elif ":" in planning and planning.split(":", 1)[0] in ai.PROVIDERS:
            db.set_setting(conn, "planning_model", planning)
        if form.get("planning_effort") in ai.EFFORTS:
            db.set_setting(conn, "planning_effort", form["planning_effort"])
    return RedirectResponse("/settings?saved=options", status_code=303)


# ------------------------------------------------------------------ JSON API

@app.post("/api/linkedin/connect")
def linkedin_connect():
    missing = linkedin_session.playwright_available()
    if missing:
        return JSONResponse({"status": "failed", "message": missing + " Run ./run.sh again."}, status_code=400)
    return linkedin_session.start_login()


@app.get("/api/linkedin/status")
def linkedin_status():
    return linkedin_session.connection_info()


@app.post("/api/linkedin/disconnect")
def linkedin_disconnect():
    linkedin_session.disconnect()
    return RedirectResponse("/settings?saved=linkedin", status_code=303)


@app.post("/api/runs/collect")
def run_collect(search_id: Optional[int] = Form(None)):
    try:
        return collector.start_collect([search_id] if search_id else None)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)


@app.post("/api/runs/analyze")
def run_analyze():
    try:
        return collector.start_analyze()
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)


@app.post("/api/runs/cancel")
def run_cancel():
    collector.cancel()
    return collector.STATE.snapshot()


@app.get("/api/runs/current")
def run_current():
    return collector.STATE.snapshot()


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return RedirectResponse("/static/favicon.svg", status_code=301)


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": __version__}


# ------------------------------------------------------------------ profile

@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request):
    with db.session() as conn:
        data, cv_filename = prof.load(conn)
        settings = db.get_settings(conn)
    choice = ai.planning_choice(settings)
    return _render(request, "profile.html", profile=data, cv_filename=cv_filename, skill_levels=prof.SKILL_LEVELS,
                   language_levels=prof.LANGUAGE_LEVELS, has_ai_key=choice is not None,
                   ai_provider=f"{ai.PROVIDERS[choice['provider']]} ({choice['model']})" if choice else "Anthropic or OpenAI")


@app.post("/api/profile")
async def save_profile(request: Request):
    try:
        data = await request.json()
    except ValueError:
        return JSONResponse({"error": "Invalid data"}, status_code=400)
    if not isinstance(data, dict):
        return JSONResponse({"error": "Invalid data"}, status_code=400)
    with db.session() as conn:
        saved = prof.save(conn, data)
    return {"ok": True, "profile": saved}


@app.post("/api/profile/cv")
async def import_cv(file: UploadFile = File(...)):
    content = await file.read(prof.MAX_CV_BYTES + 1)  # extract_cv_text rejects anything over the limit
    try:
        text = prof.extract_cv_text(file.filename or "cv", content)
    except prof.CVError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    with db.session() as conn:
        settings = db.get_settings(conn)
        prof.save_cv(conn, file.filename or "cv", content, text)
        existing, _ = prof.load(conn)
    if not ai.has_key(settings):
        return JSONResponse({"error": f"CV saved, but reading it needs your {ai.PROVIDERS[ai.current_provider(settings)]} API key "
                                      "(Settings). You can also fill the profile by hand."}, status_code=400)
    try:
        analyzer = ai.make_analyzer(settings, concurrency=1, purpose="planning")
    except ai.AIError as exc:
        return JSONResponse({"error": f"CV saved, but it can't be read yet: {exc}"}, status_code=400)
    try:
        parsed = await prof.parse_cv_with_ai(analyzer, text)
    except ai.AIError as exc:
        return JSONResponse({"error": f"Couldn't analyse the CV: {exc}"}, status_code=502)
    finally:
        await analyzer.aclose()
    merged = prof.merge_profiles(existing, parsed)
    found = {k: len(parsed.get(k, [])) for k in ("experience", "education", "skills", "languages", "certifications", "projects")}
    return {"ok": True, "profile": merged, "found": found, "filename": file.filename}


# ------------------------------------------------------------------ learning plan

@app.get("/plan", response_class=HTMLResponse)
def plan_page(request: Request, id: Optional[int] = None):
    with db.session() as conn:
        settings = db.get_settings(conn)
        window = db.int_setting(settings, "active_window_days")
        data, _ = prof.load(conn)
        plan = planner.load_plan(conn, id)
        plans = planner.list_plans(conn)
        counts = repo.dashboard_counts(conn, window)
        preview = None
        if not plan and prof.is_filled(data):
            market = planner.market_for_profile(conn, data, window)
            preview = {"market": market, "gaps": planner.gap_analysis(data, market)}
    choice = ai.planning_choice(settings)
    return _render(request, "plan.html", plan=plan, plans=plans, profile=data, has_profile=prof.is_filled(data),
                   has_ai_key=choice is not None, ai_provider=ai.PROVIDERS[ai.current_provider(settings)],
                   planning_options=ai.planning_options(settings), planning_current=f"{choice['provider']}:{choice['model']}" if choice else "",
                   planning_effort=settings.get("planning_effort") or "high", efforts=ai.EFFORTS,
                   counts=counts, preview=preview, skill_levels=prof.SKILL_LEVELS)


@app.post("/api/plan/generate")
async def plan_generate(request: Request):
    try:
        body = await request.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    with db.session() as conn:
        # Remember the chosen model/effort as the new default for profile analysis and plans.
        model = str(body.get("model") or "")
        if ":" in model and model.split(":", 1)[0] in ai.PROVIDERS:
            db.set_setting(conn, "planning_model", model)
        if body.get("effort") in ai.EFFORTS:
            db.set_setting(conn, "planning_effort", body["effort"])
        settings = db.get_settings(conn)
        data, _ = prof.load(conn)
    if not prof.is_filled(data):
        return JSONResponse({"error": "Fill in your profile first (at least skills or experience)."}, status_code=400)
    if ai.planning_choice(settings) is None:
        return JSONResponse({"error": "Add an Anthropic or OpenAI API key in Settings first."}, status_code=400)
    saved = settings.get("planning_model") or ""
    if ":" in saved and not ai.api_key_for(settings, saved.split(":", 1)[0]):
        return JSONResponse({"error": f"{saved.split(':', 1)[1]} needs your {ai.PROVIDERS[saved.split(':', 1)[0]]} API key (Settings)."}, status_code=400)
    analyzer = ai.make_analyzer(settings, concurrency=1, purpose="planning")
    conn = db.connect()
    try:
        plan_id = await planner.generate_plan(conn, analyzer, data, db.int_setting(settings, "active_window_days"))
        conn.commit()
    except ai.AIError as exc:
        return JSONResponse({"error": f"Couldn't create the plan: {exc}"}, status_code=502)
    finally:
        conn.close()
        await analyzer.aclose()
    return {"ok": True, "id": plan_id}


@app.post("/api/plan/{plan_id}/items/{item_id}")
async def plan_item_status(plan_id: int, item_id: str, request: Request):
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "Invalid data"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "Invalid data"}, status_code=400)
    try:
        with db.session() as conn:
            planner.set_progress(conn, plan_id, item_id, str(body.get("status")))
            plan = planner.load_plan(conn, plan_id)
    except ValueError:
        return JSONResponse({"error": "Invalid status"}, status_code=400)
    return {"ok": True, "progress_pct": plan["plan"]["progress_pct"] if plan else 0}
