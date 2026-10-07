# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

JobFinder is a local, single-user FastAPI app (http://127.0.0.1:8765). It collects software jobs in Austria from
karriere.at, LinkedIn and Adzuna, uses an LLM to pull out the skills each job asks for, and reports skill demand
per role and level. It also has a CV-based profile, job match scores and an AI-generated learning plan.
See README.md for the user-facing feature description.

## Commands

```bash
./run.sh                                   # creates .venv, installs deps when requirements.txt changes, starts uvicorn on :8765
source .venv/bin/activate
pip install -r requirements-dev.txt        # pytest is not in requirements.txt
pytest -q                                  # all tests
pytest -q tests/test_parsers.py::test_karriere_last_page_has_no_next  # single test
```

There is no linter or build step. The code targets Python 3.9+, so keep `from __future__ import annotations` and
`typing` generics (`List`, `Dict`, `Optional`) as the existing modules do.

## Architecture

**Request flow.** `app/main.py` serves the server-rendered Jinja pages (`app/templates/`) and a small JSON API that
the plain JS in `app/static/` polls. Template globals and filters (`bar`, `markdown`, `fromjson`) are registered in
`main.py`.

**Security (`app/security.py`).** The app listens on localhost, but any website in the browser can still send it
requests, so a middleware refuses unknown `Host` headers (DNS rebinding) and cross-site writes (`Origin` /
`Sec-Fetch-Site`), and sets a strict CSP (`script-src 'self'`). Consequences: no inline JS (`onclick=`,
`javascript:` URLs). Put behavior in `app/static/*.js` with `data-*` hooks (`data-confirm`, `data-busy`, `data-back`,
`data-navigate`, `data-run`). Render external URLs with the `| safe_url` filter and AI Markdown with `| markdown`,
which escapes raw HTML. Tests use host `testserver`, which `tests/conftest.py` allows through `JOBFINDER_ALLOWED_HOSTS`.

**Background runs (`app/collector.py`).** "Collect" and "Analyse" each run in a daemon thread that calls
`asyncio.run(...)`. Progress lives in the module-level `STATE` (`RunState`, guarded by a lock). The UI polls that
state, and the finished run is saved to the `runs` table. Only one run can be active at a time. `db.init_db()` marks
any run left in `running` as `failed` on startup.

**Pipeline.**
1. Sources (`app/sources/`) subclass `JobSource`. `search()` yields batches of `RawJob`, and `fetch_detail()`
   fills in the full description. HTTP goes through `PoliteClient`, which adds jittered minimum delays and retries
   on 429/5xx. Raise `AuthRequired` or `Blocked` (subclasses of `SourceError`) for errors the user should see.
   LinkedIn's signed-in mode drives a persistent Playwright browser profile (`linkedin_session.py`).
2. `repo.upsert_listing` deduplicates across sources by `classify.fingerprint(title, company)`. One `jobs` row
   can have several `listings` rows, and the better or fuller description wins. `classify.py` gives a rule-based
   category, seniority and job type first (`class_source='rules'`).
3. AI analysis then processes jobs with `ai_status` `pending`/`error` that are inside the active window
   (`active_window_days`, measured from the latest collection, not from today). `repo.save_ai_result` overwrites
   the classification (`class_source='ai'`) and stores the skills.
4. `reports.py` aggregates skills per (category, seniority, job_type). `planner.py` does gap analysis, match
   scores and the learning plan.

**AI layer (`app/ai.py`).** `BaseAnalyzer` is provider-neutral: `structured(name, description, schema, system,
prompt)` returns JSON, and `complete()` returns text. `AnthropicAnalyzer` uses structured outputs
(`output_config.format`) instead of forced tool use, because the newest Claude models don't support forced tool
use. It also sends `effort` and retries without it once if the model rejects it (for example Haiku 4.5). `OpenAIAnalyzer` uses the Responses API
with a strict JSON schema (`strict_json_schema` / `openai_format`). Always create analyzers through
`ai.make_analyzer(settings, purpose=...)`: `purpose="jobs"` uses the fast job-analysis model, and
`purpose="planning"` uses the separate model and effort chosen in Settings for the profile and plan (default effort `high`). Skill names are normalised through
`ALIASES` / `canonical_skill`, so add synonyms there.

**Learning plan invariants (`planner.py`, `learning_resources.py`).** Urgency comes from data (`gap_analysis`:
mention rate × required rate × gap; High ≥ 30, Medium ≥ 12). The AI may only reorder or justify it. Roadmap and
certification choices are restricted to catalog ids through a dynamic enum schema (`plan_schema`).
`postprocess_plan` replaces any URL that is not in the verified catalog with a search link. Keep that guarantee
when you change the plan output. Retired certifications are excluded from the catalog on purpose.

**Storage.**
- SQLite lives at `data/jobfinder.db` (`db.py`, plus `profile.ensure_table` and `planner.ensure_tables`).
- The schema is only `CREATE TABLE IF NOT EXISTS`, and there is no migration step. A new column on an existing
  table won't reach existing databases unless you add an explicit migration.
- Settings are key/value rows with defaults in `db.DEFAULT_SETTINGS`.
- API keys go to the macOS Keychain (`secrets_store.py`), falling back to `data/secrets.json`.
- All paths come from `app/config.py`. `JOBFINDER_DATA_DIR` overrides the data directory.

## Tests

- `tests/conftest.py` sets `JOBFINDER_NO_KEYRING=1`.
- The `tmp_data` fixture points every `config` path at a temp dir and runs `db.init_db()`.
- Parser tests run against real captured responses in `tests/fixtures/`. When a site changes its markup, capture a
  new fixture and update the parser.
- Pipeline and page tests monkeypatch `collector._build_sources` and `ai.make_analyzer` with fakes and use
  FastAPI's `TestClient`, so they never touch the network.

## UI changes

The visual system follows `DESIGN.md`: pill buttons (black `.btn-primary` for main actions), cobalt `--primary`
kept for data and selection, 16px cards, and one dark `.strip` hero on the Jobs page. Montserrat is self-hosted in
`app/static/fonts/` (no font CDN). The tokens live at the top of `app/static/app.css`, with derived dark-mode values.
Bump `__version__` in `app/__init__.py` after CSS/JS changes, because it busts the static-file cache.

After any UI change (templates in `app/templates/`, styles or scripts in `app/static/`), verify it with Playwright:
start the app with `./run.sh` (serves http://127.0.0.1:8765), open the affected pages, take screenshots at desktop
and mobile widths, check the browser console for errors, and fix any issues before finishing.
