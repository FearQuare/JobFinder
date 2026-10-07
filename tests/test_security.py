from fastapi.testclient import TestClient

from app import db, security


def test_safe_url_only_allows_http():
    assert security.safe_url("https://www.karriere.at/jobs/1") == "https://www.karriere.at/jobs/1"
    assert security.safe_url("http://example.com") == "http://example.com"
    assert security.safe_url("javascript:alert(1)") == "#"
    assert security.safe_url(" JavaScript:alert(1)") == "#"
    assert security.safe_url("data:text/html,hi") == "#"
    assert security.safe_url("") == "#"
    assert security.safe_url(None) == "#"


def test_markdown_escapes_raw_html():
    out = security.render_markdown("**Docker** <script>alert(1)</script> <img src=x onerror=alert(1)>")
    assert "<strong>Docker</strong>" in out
    assert "<script>" not in out and "<img" not in out
    assert "&lt;script&gt;" in out


def test_unknown_host_is_refused(tmp_data):
    from app.main import app

    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/healthz", headers={"host": "127.0.0.1:8765"}).status_code == 200
        assert client.get("/healthz", headers={"host": "localhost:8765"}).status_code == 200
        assert client.get("/healthz", headers={"host": "rebind.attacker.example"}).status_code == 400


def test_cross_site_writes_are_refused(tmp_data):
    from app.main import app

    with TestClient(app) as client:
        data = {"name": "Evil", "keywords": "x"}
        r = client.post("/searches", data=data, headers={"origin": "https://attacker.example"}, follow_redirects=False)
        assert r.status_code == 403
        r = client.post("/searches", data=data, headers={"sec-fetch-site": "cross-site"}, follow_redirects=False)
        assert r.status_code == 403
        r = client.post("/searches", data=data, headers={"origin": "null"}, follow_redirects=False)
        assert r.status_code == 403
        with db.session() as conn:
            assert conn.execute("SELECT COUNT(*) FROM searches WHERE name='Evil'").fetchone()[0] == 0
        # A real browser form post from the app's own page, as sent before the Referrer-Policy fix
        # (Origin: null) — Sec-Fetch-Site still marks it as same-origin.
        r = client.post("/searches", data={"name": "Mine0", "keywords": "SRE"},
                        headers={"origin": "null", "sec-fetch-site": "same-origin"}, follow_redirects=False)
        assert r.status_code == 303
        assert client.get("/").headers["referrer-policy"] == "same-origin"
        # The app's own pages (same origin) still work.
        r = client.post("/searches", data={"name": "Mine", "keywords": "SRE"},
                        headers={"origin": "http://127.0.0.1:8765", "sec-fetch-site": "same-origin"}, follow_redirects=False)
        assert r.status_code == 303


def test_security_headers_and_no_api_docs(tmp_data):
    from app.main import app

    with TestClient(app) as client:
        r = client.get("/")
        csp = r.headers["content-security-policy"]
        assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
        assert r.headers["x-content-type-options"] == "nosniff"
        assert "onclick=" not in r.text and "onsubmit=" not in r.text and "javascript:" not in r.text
        assert client.get("/docs").status_code == 404


def test_bad_query_params_dont_crash(tmp_data):
    from app.main import app

    with TestClient(app) as client:
        for q in ("search_id=abc", "posted_days=x", "category=nope", "sort=drop table", "status=weird", "page=0"):
            assert client.get("/?" + q).status_code == 200, q


def test_not_found_page_and_json(tmp_data):
    from app.main import app

    with TestClient(app) as client:
        r = client.get("/jobs/999999", headers={"accept": "text/html"})
        assert r.status_code == 404 and "Job not found" in r.text and "Go to jobs" in r.text
        r = client.get("/jobs/999999", headers={"accept": "application/json"})
        assert r.status_code == 404 and r.json() == {"error": "Job not found"}


def test_search_update_needs_name_and_keywords(tmp_data):
    from app.main import app

    with TestClient(app) as client:
        with db.session() as conn:
            sid = conn.execute("SELECT id FROM searches ORDER BY id LIMIT 1").fetchone()[0]
        r = client.post(f"/searches/{sid}", data={"name": " ", "keywords": "x"}, follow_redirects=False)
        assert r.status_code == 400
        r = client.post(f"/searches/{sid}", data={"name": "Renamed", "keywords": ""}, follow_redirects=False)
        assert r.status_code == 400
        with db.session() as conn:
            assert conn.execute("SELECT name FROM searches WHERE id=?", (sid,)).fetchone()[0] != "Renamed"


def test_plan_progress_rejects_bad_json(tmp_data):
    from app.main import app

    with TestClient(app) as client:
        r = client.post("/api/plan/1/items/i1", content=b"not json", headers={"content-type": "application/json"})
        assert r.status_code == 400
        assert client.post("/api/profile", json=["not", "an", "object"]).status_code == 400
