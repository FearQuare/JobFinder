"""End-to-end: fake sources → collector → DB → fake AI → reports → web pages."""
import asyncio
import json
import time

from fastapi.testclient import TestClient

from app import ai, collector, db, reports, repo, secrets_store
from app.sources.base import JobSource, RawJob


class FakeSource(JobSource):
    def __init__(self, key, pages, details=None, supports_detail=True):
        self.key = key
        self.pages = pages
        self.details = details or {}
        self.supports_detail = supports_detail
        self.detail_calls = []

    async def search(self, keyword, max_pages):
        for page in self.pages[:max_pages]:
            yield [RawJob(**vars(j)) for j in page]

    async def fetch_detail(self, job):
        self.detail_calls.append(job.source_id)
        d = self.details.get(job.source_id)
        if d:
            job.description = d
            job.description_is_full = True
        return job


def _karriere_pages():
    return [[
        RawJob("karriere", "k1", "https://www.karriere.at/jobs/k1", "DevOps Engineer (m/w/d)", "KNAPP", "Graz", "2026-09-20", "snippet", False, "Vollzeit"),
        RawJob("karriere", "k2", "https://www.karriere.at/jobs/k2", "Junior DevOps Engineer (w/m/d)", "ACME GmbH", "Wien", "2026-09-25", "snippet", False, "Vollzeit"),
        RawJob("karriere", "k3", "https://www.karriere.at/jobs/k3", "Werkstudent HR", "HRCo", "Wien", "2026-09-25", "snippet", False, "Teilzeit"),
    ]]


def _linkedin_pages():
    return [[
        # same job as k1 on another site → must merge
        RawJob("linkedin", "l1", "https://www.linkedin.com/jobs/view/l1/", "DevOps Engineer (all genders)", "KNAPP AG", "Graz, Styria, Austria", "2026-09-19"),
        RawJob("linkedin", "l2", "https://www.linkedin.com/jobs/view/l2/", "Senior Platform Engineer", "Bitpanda", "Vienna", "2026-09-26"),
    ]]


FAKE_AI = {
    "DevOps Engineer (m/w/d)": ("devops_cloud", "mid", [("Kubernetes", True), ("Terraform", True), ("Python", False)]),
    "Junior DevOps Engineer (w/m/d)": ("devops_cloud", "junior", [("Docker", True), ("Linux", True), ("Kubernetes", False)]),
    "Senior Platform Engineer": ("devops_cloud", "senior", [("Kubernetes", True), ("AWS", True)]),
    "Werkstudent HR": ("other", "entry", []),
}


class FakeAnalyzer:
    provider = "anthropic"

    def __init__(self, *a, **k):
        self.model = "fake-model"

    async def analyse_job(self, job):
        cat, sen, skills = FAKE_AI[job["title"]]
        return ai.normalise_result({
            "category": cat, "seniority": sen, "job_type": "full_time", "years_experience_min": 2,
            "education": "bachelor", "remote_policy": "hybrid",
            "skills": [{"name": n, "type": "tool_platform", "required": r} for n, r in skills],
            "languages": [{"language": "German", "level": "B2", "required": True}],
            "summary": "A role.",
        })

    async def summarise_group(self, title, stats):
        return f"## {title}\n\n- Kubernetes appears in most postings."

    async def aclose(self):
        pass


def _run_collection(monkeypatch, karriere_src, linkedin_src):
    monkeypatch.setattr(collector, "_build_sources", lambda settings, wanted: {"karriere": karriere_src, "linkedin": linkedin_src})
    monkeypatch.setattr(ai, "make_analyzer", lambda settings, concurrency=None: FakeAnalyzer())
    secrets_store.set_secret("anthropic_api_key", "sk-test")
    with db.session() as conn:
        conn.execute("UPDATE searches SET enabled=0 WHERE id != 1")
        conn.execute("UPDATE searches SET keywords=? WHERE id=1", (json.dumps(["DevOps"]),))
    collector.start_collect()
    for _ in range(100):
        if not collector.STATE.running:
            break
        time.sleep(0.05)
    return collector.STATE.snapshot()


def test_full_pipeline(tmp_data, monkeypatch):
    karriere_src = FakeSource("karriere", _karriere_pages(), details={"k1": "Full text: Kubernetes, Terraform", "k2": "Full text: Docker"})
    linkedin_src = FakeSource("linkedin", _linkedin_pages(), details={"l2": "Kubernetes and AWS"})
    state = _run_collection(monkeypatch, karriere_src, linkedin_src)
    assert state["status"] == "done", state["log"]

    with db.session() as conn:
        jobs = conn.execute("SELECT * FROM jobs ORDER BY id").fetchall()
        assert len(jobs) == 4, "k1 and l1 are the same job and must be merged"
        knapp = conn.execute("SELECT * FROM jobs WHERE company='KNAPP'").fetchone()
        assert len(repo.job_listings(conn, knapp["id"])) == 2
        assert knapp["description"] == "Full text: Kubernetes, Terraform"
        assert all(j["ai_status"] == "done" for j in jobs)
        assert conn.execute("SELECT category FROM jobs WHERE title='Werkstudent HR'").fetchone()[0] == "other"
    assert sorted(karriere_src.detail_calls) == ["k1", "k2", "k3"]
    assert state["counters"]["new_jobs"] == 4
    assert state["counters"]["analysed"] == 4

    with db.session() as conn:
        stats = reports.group_stats(conn, "devops_cloud", None, None, 14)
        assert stats["job_count"] == 3
        top = {s["skill"]: s for s in stats["skills"]}
        assert top["Kubernetes"]["count"] == 3 and top["Kubernetes"]["pct"] == 100
        assert top["Kubernetes"]["required_pct"] == 67
        assert stats["languages"][0]["language"] == "German"
        assert stats["experience"]["median_years"] == 2
        ov = reports.overview(conn, 14)
        assert [(r["category"], r["seniority"]) for r in ov] == [("devops_cloud", "junior"), ("devops_cloud", "mid"), ("devops_cloud", "senior")]

    # second run: nothing new, no repeated detail fetches, no repeated analysis
    karriere_src2 = FakeSource("karriere", _karriere_pages())
    linkedin_src2 = FakeSource("linkedin", _linkedin_pages())
    state2 = _run_collection(monkeypatch, karriere_src2, linkedin_src2)
    assert state2["counters"]["new_jobs"] == 0
    assert karriere_src2.detail_calls == []
    assert state2["counters"]["analysed"] == 0


def test_pages_render(tmp_data, monkeypatch):
    from app.main import app

    karriere_src = FakeSource("karriere", _karriere_pages(), details={"k1": "Kubernetes"})
    linkedin_src = FakeSource("linkedin", _linkedin_pages())
    _run_collection(monkeypatch, karriere_src, linkedin_src)

    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200 and "Junior DevOps Engineer" in r.text
        assert "Werkstudent HR" not in r.text  # non-software hidden by default
        assert "Werkstudent HR" in client.get("/?hide_other=0").text
        assert "Senior Platform Engineer" in client.get("/?seniority=senior").text
        assert "Junior DevOps" not in client.get("/?seniority=senior").text
        assert "Senior Platform" in client.get("/?skill=AWS").text
        assert client.get("/?q=bitpanda").text.count("job-title") == 1
        with db.session() as conn:
            jid = conn.execute("SELECT id FROM jobs WHERE company='KNAPP'").fetchone()[0]
        r = client.get(f"/jobs/{jid}")
        assert r.status_code == 200 and "Kubernetes" in r.text and "Open on karriere.at" in r.text and "Open on LinkedIn" in r.text
        r = client.get("/insights")
        assert r.status_code == 200 and "DevOps / Cloud / SRE" in r.text and "Kubernetes" in r.text
        r = client.get("/insights?category=devops_cloud&seniority=junior")
        assert r.status_code == 200 and "Docker" in r.text
        r = client.post("/insights/summary", data={"category": "devops_cloud", "seniority": "", "job_type": ""}, follow_redirects=True)
        assert r.status_code == 200 and "appears in most postings" in r.text
        assert client.get("/searches").status_code == 200
        r = client.get("/settings")
        assert r.status_code == 200 and "Saved (" in r.text
        r = client.post("/searches", data={"name": "My search", "keywords": "Cloud Engineer\nSRE, Platform", "sources": ["karriere"]}, follow_redirects=True)
        assert r.status_code == 200 and "My search" in r.text
        with db.session() as conn:
            row = conn.execute("SELECT keywords, sources FROM searches WHERE name='My search'").fetchone()
        assert json.loads(row["keywords"]) == ["Cloud Engineer", "SRE", "Platform"]
        assert json.loads(row["sources"]) == ["karriere"]
        r = client.post("/settings/options", data={"karriere_max_pages": "5", "linkedin_mode": "logged_in", "ai_model": "claude-x"}, follow_redirects=True)
        assert r.status_code == 200
        with db.session() as conn:
            s = db.get_settings(conn)
        assert s["karriere_max_pages"] == "5"
        assert s["linkedin_mode"] == "public"  # can't switch to logged-in without connecting
        assert s["ai_model"] == "claude-x"
        assert client.get("/api/runs/current").json()["status"] in ("done", "idle")
        assert client.get("/healthz").json()["ok"]


def test_ai_auth_error_stops_analysis(tmp_data, monkeypatch):
    class BadKey(FakeAnalyzer):
        async def analyse_job(self, job):
            raise ai.AIAuthError("The Anthropic API key was rejected.")

    karriere_src = FakeSource("karriere", _karriere_pages())
    linkedin_src = FakeSource("linkedin", [])
    monkeypatch.setattr(collector, "_build_sources", lambda s, w: {"karriere": karriere_src, "linkedin": linkedin_src})
    secrets_store.set_secret("anthropic_api_key", "bad")
    monkeypatch.setattr(ai, "make_analyzer", lambda settings, concurrency=None: BadKey())
    collector.start_collect()
    for _ in range(100):
        if not collector.STATE.running:
            break
        time.sleep(0.05)
    state = collector.STATE.snapshot()
    assert any("key was rejected" in line for line in state["log"])
    with db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs WHERE ai_status='pending'").fetchone()[0] == 3
