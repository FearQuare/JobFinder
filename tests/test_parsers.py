import json
from datetime import date

from app.sources import adzuna, karriere, linkedin
from app.sources.base import RawJob, html_to_text, parse_relative_date


def test_karriere_search_parses_jobs_and_skips_ads(fixture_text):
    jobs, next_page, total = karriere.parse_search_json(json.loads(fixture_text("karriere_search.json")))
    assert [j.source_id for j in jobs] == ["7834496", "7880389", "7854077"]
    assert next_page == 3
    assert total == 138
    first = jobs[0]
    assert first.title == "DevOps Engineer (m/w/d)"
    assert first.company == "KNAPP"
    assert first.location == "Hart bei Graz"
    assert first.url == "https://www.karriere.at/jobs/7834496"
    assert first.employment_raw == "Vollzeit"
    assert first.salary_text == "ab 3.415,01 € monatlich"
    assert first.posted_at is not None
    assert jobs[2].posted_at == "2026-09-21"
    assert not first.description_is_full


def test_karriere_last_page_has_no_next(fixture_text):
    jobs, next_page, _ = karriere.parse_search_json(json.loads(fixture_text("karriere_last_page.json")))
    assert len(jobs) == 1 and next_page is None


def test_karriere_search_url_encodes_keyword():
    assert karriere.search_url("C# Developer", 1) == "https://www.karriere.at/jobs?keywords=C%23%20Developer"
    assert karriere.search_url("devops", 3).endswith("&page=3")


def test_karriere_detail_reads_jsonld(fixture_text):
    job = RawJob(source="karriere", source_id="7834496", url="x", title="old")
    job = karriere.parse_detail_html(fixture_text("karriere_detail.html"), job)
    assert job.title == "DevOps Engineer (m/w/d)"
    assert job.description_is_full
    assert "Kubernetes" in job.description
    assert "• Du entwickelst CI/CD-Prozesse" in job.description
    assert job.posted_at == "2026-09-23"
    assert job.employment_raw == "Vollzeit"
    assert job.location == "Hart bei Graz"
    assert job.company == "KNAPP"


def test_linkedin_guest_search(fixture_text):
    jobs = linkedin.parse_guest_search(fixture_text("linkedin_search.html"))
    assert [j.source_id for j in jobs] == ["4467097928", "4434637867"]
    assert jobs[0].company == "Österreichische Post AG"
    assert jobs[0].location == "Vienna, Vienna, Austria"
    assert jobs[0].posted_at == "2026-09-14"
    assert jobs[0].title.startswith("DevOps Engineer Container - Plattform & Automatisierung")
    assert jobs[1].posted_at == "2026-09-25"  # "--new" time class variant
    assert jobs[1].url == "https://www.linkedin.com/jobs/view/4434637867/"


def test_linkedin_guest_detail(fixture_text):
    job = RawJob(source="linkedin", source_id="4467097928", url="x")
    job = linkedin.parse_guest_detail(fixture_text("linkedin_detail.html"), job)
    assert job.title.startswith("DevOps Engineer Container")
    assert job.company == "Österreichische Post AG"
    assert job.location == "Vienna, Vienna, Austria"
    assert job.employment_raw == "Full-time"
    assert job.seniority_raw == "Not Applicable"
    assert "Docker und Kubernetes" in job.description
    assert "Show more" not in job.description
    assert job.description_is_full and not job.closed


def test_linkedin_closed_job():
    job = linkedin.parse_guest_detail(
        '<div class="show-more-less-html__markup">x</div><span>No longer accepting applications</span>',
        RawJob(source="linkedin", source_id="1", url="x"),
    )
    assert job.closed


def test_linkedin_extract_ids_from_logged_in_markup():
    html = (
        '<li data-occludable-job-id="4467097928"></li>'
        '<div data-job-id="4434637867"></div>'
        '<a href="/jobs/view/4468906579/?refId=x">x</a>'
        '<code>{"entityUrn":"urn:li:fsd_jobPosting:4467045753"}</code>'
        '<a href="/jobs/view/4467097928/">dupe</a>'
    )
    assert linkedin.extract_job_ids(html) == ["4467097928", "4434637867", "4467045753", "4468906579"]


def test_linkedin_search_urls():
    url = linkedin.guest_search_url("DevOps Engineer", 20, 30)
    assert "keywords=DevOps+Engineer" in url and "location=Austria" in url and "start=20" in url and "f_TPR=r2592000" in url
    assert "f_TPR" not in linkedin.guest_search_url("x", 0, 0)


def test_adzuna_parse():
    payload = {"results": [{
        "id": "123", "title": "<strong>DevOps</strong> Engineer", "company": {"display_name": "ACME"},
        "location": {"display_name": "Wien, Österreich"}, "created": "2026-09-20T10:00:00Z",
        "description": "Kubernetes, <em>Terraform</em> …", "redirect_url": "https://www.adzuna.at/land/ad/123",
        "salary_min": 50000, "salary_max": 60000, "salary_is_predicted": "0", "contract_time": "full_time",
    }, {"id": "124", "title": "Predicted salary job", "salary_min": 40000, "salary_max": 40000, "salary_is_predicted": "1"}]}
    jobs = adzuna.parse_results(payload)
    assert jobs[0].title == "DevOps Engineer"
    assert jobs[0].posted_at == "2026-09-20"
    assert jobs[0].salary_text == "50.000 – 60.000 € / Jahr"
    assert jobs[0].description == "Kubernetes, Terraform …"
    assert jobs[1].salary_text is None


def test_relative_dates():
    today = date(2026, 9, 29)
    assert parse_relative_date("vor 6 Tagen veröffentlicht", today) == "2026-09-23"
    assert parse_relative_date("vor 1 Tag veröffentlicht", today) == "2026-09-28"
    assert parse_relative_date("vor 2 Wochen", today) == "2026-09-15"
    assert parse_relative_date("heute veröffentlicht", today) == "2026-09-29"
    assert parse_relative_date("gestern", today) == "2026-09-28"
    assert parse_relative_date("21.9.2026", today) == "2026-09-21"
    assert parse_relative_date("2 weeks ago", today) == "2026-09-15"
    assert parse_relative_date("a month ago", today) == "2026-08-30"
    assert parse_relative_date("something else", today) is None


def test_html_to_text_keeps_structure():
    text = html_to_text("<p>Intro</p><ul><li>One</li><li>Two</li></ul><p>End<br>line</p>")
    assert text == "Intro\n\n• One\n\n• Two\n\nEnd\nline" or text.splitlines()[0] == "Intro"
    assert "• One" in text and "• Two" in text
