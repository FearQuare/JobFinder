"""karriere.at — Austria's largest job board.

The search page returns JSON when asked with an XHR Accept header (the same call the
site's own "Weitere Jobs anzeigen" button makes), and each job page carries a
schema.org JobPosting block with the full description.
"""
from __future__ import annotations

import json
from typing import AsyncIterator, List, Optional, Tuple
from urllib.parse import quote

from bs4 import BeautifulSoup

from .base import JobSource, PoliteClient, RawJob, SourceError, clean, html_to_text, iso_date, parse_relative_date

BASE = "https://www.karriere.at"

_EMPLOYMENT_MAP = {
    "FULL_TIME": "Vollzeit",
    "PART_TIME": "Teilzeit",
    "INTERN": "Praktikum",
    "CONTRACTOR": "Freelance",
    "TEMPORARY": "Befristet",
    "OTHER": "Andere",
}


def search_url(keyword: str, page: int) -> str:
    url = f"{BASE}/jobs?keywords={quote(keyword)}"
    return url + (f"&page={page}" if page > 1 else "")


def parse_search_json(payload: dict) -> Tuple[List[RawJob], Optional[int], Optional[int]]:
    """Returns (jobs, next_page, total_count)."""
    data = payload.get("data") or {}
    lst = data.get("jobsSearchList") or {}
    items = ((lst.get("activeItems") or {}).get("items")) or []
    jobs: List[RawJob] = []
    for item in items:
        ji = item.get("jobsItem") if isinstance(item, dict) else None
        if not ji or not ji.get("id"):
            continue  # ads / disruptors
        company = (ji.get("company") or {}).get("name")
        locations = ", ".join(l.get("name", "") for l in (ji.get("locations") or []) if l.get("name"))
        jobs.append(
            RawJob(
                source="karriere",
                source_id=str(ji["id"]),
                url=ji.get("link") or f"{BASE}/jobs/{ji['id']}",
                title=clean(ji.get("title")) or "",
                company=clean(company),
                location=clean(locations) or clean((ji.get("company") or {}).get("mainLocation")),
                posted_at=parse_relative_date(ji.get("date")),
                description=clean(ji.get("summary") or ji.get("snippet")),
                description_is_full=False,
                employment_raw=clean(ji.get("employmentTypes")),
                salary_text=clean(ji.get("salary")),
                extra={"home_office": bool(ji.get("isHomeOffice"))},
            )
        )
    more = lst.get("loadMoreJobsButton") or {}
    next_page = more.get("next") if more.get("active") and more.get("next") else None
    total = None
    header = lst.get("jobsListHeader") or {}
    try:
        total = int(str(header.get("count", "")).replace(".", ""))
    except ValueError:
        pass
    return jobs, (int(next_page) if next_page else None), total


def parse_detail_html(html: str, job: RawJob) -> RawJob:
    soup = BeautifulSoup(html, "html.parser")
    posting = None
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text() or "")
        except ValueError:
            continue
        candidates = data if isinstance(data, list) else [data]
        for c in candidates:
            if isinstance(c, dict) and c.get("@type") == "JobPosting":
                posting = c
                break
        if posting:
            break
    if not posting:
        return job
    job.title = clean(posting.get("title")) or job.title
    job.description = html_to_text(posting.get("description")) or job.description
    job.description_is_full = bool(posting.get("description"))
    job.posted_at = iso_date(posting.get("datePosted")) or job.posted_at
    org = posting.get("hiringOrganization") or {}
    if isinstance(org, dict) and org.get("name"):
        job.company = clean(org["name"])
    locs = posting.get("jobLocation") or []
    if isinstance(locs, dict):
        locs = [locs]
    names = []
    for loc in locs:
        addr = (loc or {}).get("address") or {}
        if addr.get("addressLocality"):
            names.append(addr["addressLocality"])
    if names:
        job.location = ", ".join(dict.fromkeys(names))
    emp = posting.get("employmentType")
    if emp:
        emp_list = emp if isinstance(emp, list) else [emp]
        job.employment_raw = ", ".join(_EMPLOYMENT_MAP.get(e, e) for e in emp_list)
    return job


class KarriereSource(JobSource):
    key = "karriere"

    def __init__(self) -> None:
        self.http = PoliteClient(min_interval=0.8)

    async def search(self, keyword: str, max_pages: int) -> AsyncIterator[List[RawJob]]:
        page = 1
        while page and page <= max_pages:
            resp = await self.http.get(
                search_url(keyword, page),
                headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            )
            if resp.status_code != 200:
                raise SourceError(f"karriere.at search returned HTTP {resp.status_code}")
            try:
                payload = resp.json()
            except ValueError as exc:
                raise SourceError("karriere.at returned an unexpected response (not JSON); the site may have changed") from exc
            jobs, next_page, _ = parse_search_json(payload)
            yield jobs
            if not jobs:
                break
            page = next_page if next_page and next_page > page else 0

    async def fetch_detail(self, job: RawJob) -> RawJob:
        resp = await self.http.get(f"{BASE}/jobs/{job.source_id}")
        if resp.status_code in (404, 410):
            job.closed = True
            return job
        if resp.status_code != 200:
            raise SourceError(f"karriere.at job {job.source_id} returned HTTP {resp.status_code}")
        return parse_detail_html(resp.text, job)

    async def aclose(self) -> None:
        await self.http.aclose()
