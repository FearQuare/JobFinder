# JobFinder (V1)

A personal, local web app that collects **software jobs in Austria** from several job sites and reports
**which skills employers ask for** per role and level ("junior DevOps", "senior QA", "working student", …).

Runs only on your laptop at <http://127.0.0.1:8765>. Your data and keys never leave your machine,
except to call the job sites and the AI API.

## Start

```bash
cd ~/Projects/JobFinder
./run.sh
```

The first start creates a Python virtual environment and installs everything (a minute or two).
Later starts are instant. Needs Python 3.9+ (`python3 --version`; install with `brew install python` if missing).

Then in the app:

1. **Settings** → paste an **Anthropic** or **OpenAI API key** (for skill extraction). Optional: free **Adzuna** App ID/Key.
2. **Searches** → adjust the keywords (six searches are pre-filled: DevOps, Software Engineering,
   Backend/Frontend/Full-stack, QA, Data/ML, Working student & internships).
3. Click **Collect jobs**. The first run takes a while (it fetches every job description once, politely);
   later runs only fetch what's new.
4. **Jobs** lists what's open now, with filters (role type, level, contract type, source, skill, …).
   **Skill insights** shows the most requested skills per role and level, language requirements
   (German level!), typical experience, and an AI-written summary on request.

## Profile, job matching and learning plan

- **My profile** — import your CV (PDF/Word/text; the AI fills in experience, education, skills with an estimated
  level, languages, certificates, projects — you review and save) or fill it in by hand. Set target roles, level,
  contract type and how many hours per week you can study.
- **Match %** on the Jobs list: how well your skills cover each job's required (×2) and nice-to-have (×1) skills;
  jobs that require a language level you don't have are marked ("needs German B2") and scored lower.
  Sort by **Best match for me**.
- **Learning plan** — compares your profile with the analysed postings for your target roles and builds a
  prioritised roadmap:
  - Urgency is computed from the data first: how often target postings mention a skill × how often it is
    *required* × how big your gap is (languages: typical required level vs. yours). High ≥ 30, Medium ≥ 12, else Low.
    The AI keeps those unless it gives a reason, then orders everything into phases (foundations first).
  - Each item: why (citing the data), current → target level, estimated hours, how to study it, a practice
    project, and where to learn it. Links come from a checked catalog (official docs, free courses, roadmap.sh);
    any link the AI invents is replaced with a search link, so there are no broken or made-up URLs.
  - Timeline from your weekly hours (languages run in parallel), progress tracking per item, plan history.
  - roadmap.sh: the app links to the matching roadmap.sh roadmaps instead of copying them — their license allows
    personal use and linking, not republishing.
  - **Certifications that make you stand out** — picked from a checked list of 25 current certifications (AWS, Azure,
    Google Cloud, CNCF/Kubernetes, HashiCorp, Linux Foundation, Red Hat, GitHub, ISTQB, CompTIA, ISC2, Databricks,
    Scrum.org, and ÖSD/Goethe German certificates) with exam fee, level, prerequisites, prep hours, the phase to take
    it in, and how many of your target postings mention it. Retired certificates (e.g. AZ-204, AI-102) are excluded.
  - **Roadmaps & curricula** from several providers — roadmap.sh, Microsoft Learn career paths, AWS Ramp-Up Guides,
    popular GitHub roadmaps/curricula (DevOps-Roadmap, 90DaysOfDevOps, OSSU, System Design Primer), Full Stack Open,
    The Odin Project, freeCodeCamp, Test Automation University, DataTalksClub Zoomcamp, Google SRE books,
    Cloud Resume Challenge, Kubernetes The Hard Way. The AI picks the most useful ones for you and explains how to use each.
- **Choose the AI model for profile analysis and plans** (Settings or right on the Learning plan page), separately
  from the fast model used for job analysis: Claude Fable 5.1 / Opus 5.5 / Sonnet 5.5 / Haiku 4.5 or
  GPT-6 Astra / 6.1 Sol / 6 Luna (or any other model id), plus thinking effort (low/medium/high). Rough cost per plan
  is shown next to each model. Claude models use structured outputs (`output_config.format`), because the newest
  Claude models don't support forced tool use.

## Sources

| Source | How | Account needed |
|---|---|---|
| karriere.at | The site's own search JSON + the structured job data on each job page | No |
| LinkedIn | Public job search (default), or signed in with your account (optional) | Optional |
| Adzuna | Official API (aggregates many Austrian boards; only description snippets) | Free API key |

The same job found on several sites is stored once and shows all its links.

### LinkedIn and your account

Public mode needs no account and covers most postings. **Connect LinkedIn** (Settings) opens a real browser
window where *you* sign in — the app never sees or stores your password; it keeps that browser session in
`data/linkedin-browser-profile/` and reuses it. Signed-in mode loads search results as you see them logged in
(more results per search).

LinkedIn's User Agreement prohibits automated access, and accounts can be restricted if detected. The app
waits between requests to keep volumes low, but the risk applies to the account you connect. You can
disconnect at any time (this deletes the saved session).

## AI analysis

Each job description is sent once to the AI provider you choose in Settings — **Anthropic** (default model
Claude Haiku 4.5, roughly $2–4 per 1,000 jobs) or **OpenAI** (default model `gpt-6-luna`, via the Responses API
with a strict JSON schema) — and returns: role category, seniority, contract type, required vs. nice-to-have
skills, languages with level, years of experience, education, and work model. Results are cached, so only new
jobs cost anything. Change the model in Settings.

## Where things are stored

- `data/jobfinder.db` — SQLite database (jobs, listings, skills, settings)
- API keys (Anthropic, OpenAI, Adzuna) — macOS Keychain (service "JobFinder"); falls back to `data/secrets.json` (mode 600) if no keychain
- `data/linkedin-browser-profile/` — only if you connect LinkedIn
- `data/cv/` — the CV you uploaded; your profile and plans are in the database

Delete `data/` to start fresh.

## Project layout

```
app/
  main.py            FastAPI routes (pages + JSON API for runs)
  collector.py       background collection + AI analysis runs, progress
  sources/           karriere.py, linkedin.py, linkedin_session.py, adzuna.py, base.py
  classify.py        title-based classification + duplicate fingerprinting
  ai.py              Anthropic extraction (tool-use JSON) + group summaries
  reports.py         skill aggregation per role/level
  repo.py, db.py     storage
  security.py        host/origin checks, security headers, safe URL + Markdown rendering
  templates/, static/  UI
tests/               parser tests on real captured responses, full pipeline + page tests
```

Run the tests: `source .venv/bin/activate && pip install pytest && pytest -q`

## Known limits (V1)

- Austria only; software roles only (the search keywords decide what's collected).
- Job sites change their pages; if a source suddenly returns 0 results, its parser needs an update
  (tests in `tests/fixtures` show the expected shapes).
- "Open now" means seen within the last 14 days of your latest collection (changeable in Settings).
