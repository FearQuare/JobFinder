"""LinkedIn jobs.

Two modes:

* public (default) — LinkedIn's public job-search pages, the ones anyone sees
  without signing in. No account involved.
* logged_in — reuses the browser session you created with "Connect LinkedIn"
  (you sign in yourself in a real browser window; the app never sees your
  password). Search pages are loaded in that session, which returns more
  results, and job details are fetched with your cookies.

Note: LinkedIn's User Agreement prohibits automated access. Keep volumes low;
the defaults here are deliberately slow. Using logged-in mode puts your own
account at risk of restriction.
"""
from __future__ import annotations

import asyncio
import re
from typing import AsyncIterator, List, Optional
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from .. import config
from .base import AuthRequired, Blocked, JobSource, PoliteClient, RawJob, SourceError, clean, html_to_text, iso_date, parse_relative_date

GUEST_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
GUEST_DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"
LOGGED_IN_SEARCH = "https://www.linkedin.com/jobs/search/"
LOCATION = "Austria"
AUSTRIA_GEO_ID = "103883259"


def job_url(job_id: str) -> str:
    return f"https://www.linkedin.com/jobs/view/{job_id}/"


def guest_search_url(keyword: str, start: int, posted_within_days: int) -> str:
    params = {"keywords": keyword, "location": LOCATION, "geoId": AUSTRIA_GEO_ID, "start": start}
    if posted_within_days > 0:
        params["f_TPR"] = f"r{posted_within_days * 86400}"
    return f"{GUEST_SEARCH}?{urlencode(params)}"


def logged_in_search_url(keyword: str, start: int, posted_within_days: int) -> str:
    params = {"keywords": keyword, "location": LOCATION, "geoId": AUSTRIA_GEO_ID}
    if posted_within_days > 0:
        params["f_TPR"] = f"r{posted_within_days * 86400}"
    if start:
        params["start"] = start
    return f"{LOGGED_IN_SEARCH}?{urlencode(params)}"


def parse_guest_search(html: str) -> List[RawJob]:
    soup = BeautifulSoup(html, "html.parser")
    jobs: List[RawJob] = []
    for card in soup.select("[data-entity-urn]"):
        urn = card.get("data-entity-urn", "")
        m = re.search(r"jobPosting:(\d+)", urn)
        if not m:
            continue
        job_id = m.group(1)
        title = card.select_one(".base-search-card__title")
        company = card.select_one(".base-search-card__subtitle")
        location = card.select_one(".job-search-card__location")
        time_el = card.select_one("time[datetime]")
        jobs.append(
            RawJob(
                source="linkedin",
                source_id=job_id,
                url=job_url(job_id),
                title=clean(title.get_text()) if title else "",
                company=clean(company.get_text()) if company else None,
                location=clean(location.get_text()) if location else None,
                posted_at=iso_date(time_el["datetime"]) if time_el else None,
            )
        )
    return jobs


_ID_PATTERNS = [
    re.compile(r"data-(?:occludable-)?job-id=\"(\d{6,})\""),
    re.compile(r"urn:li:(?:fs_normalized_jobPosting|jobPosting|fsd_jobPosting):(\d{6,})"),
    re.compile(r"/jobs/view/(?:[^\"'?/]*-)?(\d{6,})"),
    re.compile(r"currentJobId=(\d{6,})"),
]


def extract_job_ids(html: str) -> List[str]:
    """Pull job IDs out of a (logged-in) LinkedIn search page, independent of its CSS classes."""
    seen: dict = {}
    for pattern in _ID_PATTERNS:
        for m in pattern.finditer(html):
            seen.setdefault(m.group(1), None)
    return list(seen)


def parse_guest_detail(html: str, job: RawJob) -> RawJob:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.select_one(".top-card-layout__title, .topcard__title")
    if title and clean(title.get_text()):
        job.title = clean(title.get_text())
    company = soup.select_one(".topcard__org-name-link, .topcard__flavor a")
    if company and clean(company.get_text()):
        job.company = clean(company.get_text())
    location = soup.select_one(".topcard__flavor--bullet")
    if location and clean(location.get_text()):
        job.location = clean(location.get_text())
    if not job.posted_at:
        posted = soup.select_one(".posted-time-ago__text")
        if posted:
            job.posted_at = parse_relative_date(posted.get_text())
    markup = soup.select_one(".show-more-less-html__markup") or soup.select_one(".description__text")
    if markup:
        job.description = html_to_text(markup.decode_contents())
        job.description_is_full = True
    for item in soup.select(".description__job-criteria-item"):
        header = item.select_one("h3")
        value = item.select_one("span")
        if not header or not value:
            continue
        key = clean(header.get_text()).lower()
        val = clean(value.get_text())
        if key.startswith("employment type"):
            job.employment_raw = val
        elif key.startswith("seniority level"):
            job.seniority_raw = val
    page_text = soup.get_text(" ").lower()
    if "no longer accepting applications" in page_text:
        job.closed = True
    return job


class LinkedInSource(JobSource):
    key = "linkedin"

    def __init__(self, mode: str = "public", posted_within_days: int = 30, show_browser: bool = False):
        self.mode = mode
        self.posted_within_days = posted_within_days
        self.show_browser = show_browser
        self.http = PoliteClient(min_interval=2.5, headers={"Accept": "text/html"})
        self._pw = None
        self._context = None

    # ---------- logged-in browser session ----------
    async def _browser(self):
        if self._context is not None:
            return self._context
        from . import linkedin_session

        if not linkedin_session.is_connected():
            raise AuthRequired("LinkedIn logged-in mode is on, but no LinkedIn account is connected. Connect it in Settings.")
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise SourceError("Playwright is not installed. Run ./run.sh again to install it.") from exc
        self._pw = await async_playwright().start()
        self._context = await linkedin_session.launch_async(self._pw, headless=not self.show_browser)
        return self._context

    async def _logged_in_page_ids(self, keyword: str, start: int) -> List[str]:
        context = await self._browser()
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(logged_in_search_url(keyword, start, self.posted_within_days), wait_until="domcontentloaded")
        await asyncio.sleep(3)
        if any(s in page.url for s in ("/login", "/checkpoint", "/authwall", "/uas/")):
            from . import linkedin_session

            linkedin_session.mark_disconnected("LinkedIn asked to sign in again")
            raise AuthRequired("Your LinkedIn session expired. Reconnect LinkedIn in Settings.")
        # The results list lazy-loads as it scrolls; scroll every scrollable element a few times.
        for _ in range(6):
            await page.evaluate(
                """() => { for (const el of document.querySelectorAll('*')) {
                    const s = getComputedStyle(el);
                    if ((s.overflowY === 'auto' || s.overflowY === 'scroll') && el.scrollHeight > el.clientHeight + 50) {
                        el.scrollTop = el.scrollTop + 1200; } }
                    window.scrollBy(0, 1200); }"""
            )
            await asyncio.sleep(0.8)
        return extract_job_ids(await page.content())

    # ---------- JobSource ----------
    async def search(self, keyword: str, max_pages: int) -> AsyncIterator[List[RawJob]]:
        seen: set = set()
        if self.mode == "logged_in":
            for page_no in range(max_pages):
                ids = await self._logged_in_page_ids(keyword, page_no * 25)
                new_ids = [i for i in ids if i not in seen]
                if not new_ids:
                    break
                seen.update(new_ids)
                yield [RawJob(source="linkedin", source_id=i, url=job_url(i)) for i in new_ids]
                await asyncio.sleep(2)
            return

        start = 0
        for _ in range(max_pages):
            resp = await self.http.get(guest_search_url(keyword, start, self.posted_within_days))
            if resp.status_code == 400 and start > 0:
                break  # LinkedIn returns 400 past the last page
            if resp.status_code != 200:
                raise SourceError(f"LinkedIn search returned HTTP {resp.status_code}")
            parsed = parse_guest_search(resp.text)
            jobs = [j for j in parsed if j.source_id not in seen]
            if not jobs:
                break
            seen.update(j.source_id for j in jobs)
            yield jobs
            start += len(parsed)

    async def fetch_detail(self, job: RawJob) -> RawJob:
        url = GUEST_DETAIL.format(id=job.source_id)
        if self.mode == "logged_in":
            context = await self._browser()
            await asyncio.sleep(1.5)
            resp = await context.request.get(url)
            status, text = resp.status, await resp.text()
        else:
            resp = await self.http.get(url)
            status, text = resp.status_code, resp.text
        if status in (404, 410):
            job.closed = True
            return job
        if status in (429, 999):
            raise Blocked("LinkedIn is rate-limiting requests. Try again later.")
        if status != 200:
            raise SourceError(f"LinkedIn job {job.source_id} returned HTTP {status}")
        return parse_guest_detail(text, job)

    async def aclose(self) -> None:
        await self.http.aclose()
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
