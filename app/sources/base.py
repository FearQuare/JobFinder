"""Common types and HTTP helpers for job sources."""
from __future__ import annotations

import asyncio
import random
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import AsyncIterator, List, Optional

import httpx
from bs4 import BeautifulSoup

from .. import config


class SourceError(Exception):
    """A source failed in a way worth showing to the user."""


class AuthRequired(SourceError):
    """The source needs (new) credentials or a fresh login."""


class Blocked(SourceError):
    """The site refused us (rate limit or bot protection)."""


@dataclass
class RawJob:
    source: str
    source_id: str
    url: str
    title: str = ""
    company: Optional[str] = None
    location: Optional[str] = None
    posted_at: Optional[str] = None          # ISO date (YYYY-MM-DD)
    description: Optional[str] = None        # plain text; may be only a snippet
    description_is_full: bool = False
    employment_raw: Optional[str] = None     # e.g. "Vollzeit", "Full-time", "Internship"
    seniority_raw: Optional[str] = None      # e.g. LinkedIn "Entry level"
    salary_text: Optional[str] = None
    closed: bool = False
    extra: dict = field(default_factory=dict)


class JobSource:
    key = "base"
    supports_detail = True

    async def search(self, keyword: str, max_pages: int) -> AsyncIterator[List[RawJob]]:  # pragma: no cover
        raise NotImplementedError
        yield []

    async def fetch_detail(self, job: RawJob) -> RawJob:  # pragma: no cover
        return job

    async def aclose(self) -> None:
        pass


class PoliteClient:
    """httpx client with a minimum delay between requests and retry/backoff on 429/5xx."""

    def __init__(self, min_interval: float, headers: Optional[dict] = None, max_retries: int = 3, cookies=None):
        base_headers = {"User-Agent": config.USER_AGENT, "Accept-Language": "de-AT,de;q=0.9,en;q=0.8"}
        base_headers.update(headers or {})
        self.client = httpx.AsyncClient(headers=base_headers, timeout=30, follow_redirects=True, cookies=cookies)
        self.min_interval = min_interval
        self.max_retries = max_retries
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def _wait_turn(self) -> None:
        async with self._lock:
            delay = self.min_interval * random.uniform(0.8, 1.3) - (time.monotonic() - self._last)
            if delay > 0:
                await asyncio.sleep(delay)
            self._last = time.monotonic()

    async def get(self, url: str, **kwargs) -> httpx.Response:
        attempt = 0
        while True:
            await self._wait_turn()
            try:
                resp = await self.client.get(url, **kwargs)
            except httpx.TransportError as exc:
                if attempt >= self.max_retries:
                    # Without the query string: Adzuna's URL carries the API key, and this message ends up in the run log.
                    raise SourceError(f"Network error for {url.split('?', 1)[0]}: {exc}") from exc
                attempt += 1
                await asyncio.sleep(2 ** attempt)
                continue
            if resp.status_code in (429, 500, 502, 503, 504, 999) and attempt < self.max_retries:
                attempt += 1
                retry_after = resp.headers.get("retry-after")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else 5 * 2 ** attempt
                await asyncio.sleep(min(wait, 60))
                continue
            if resp.status_code in (429, 999):
                raise Blocked(f"{httpx.URL(url).host} is rate-limiting requests (HTTP {resp.status_code}). Try again later.")
            return resp

    async def aclose(self) -> None:
        await self.client.aclose()


_BLOCK_TAGS = ("p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section")


def html_to_text(html: Optional[str]) -> str:
    """Turn job-description HTML into readable plain text, keeping line breaks and bullets."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    for li in soup.find_all("li"):
        li.insert_before("\n• ")
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_after("\n")
    text = soup.get_text()
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


_GERMAN_RELATIVE = re.compile(r"vor\s+(\d+|einer|einem|einen)\s+(Stunde|Stunden|Tag|Tagen|Woche|Wochen|Monat|Monaten)", re.I)
_EN_RELATIVE = re.compile(r"(\d+|an?|one)\s+(hour|day|week|month)s?\s+ago", re.I)


def parse_relative_date(text: Optional[str], today: Optional[date] = None) -> Optional[str]:
    """Parse 'vor 6 Tagen veröffentlicht', '21.9.2026', 'heute', '2 weeks ago' into an ISO date."""
    if not text:
        return None
    today = today or date.today()
    t = text.strip().lower()
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", t)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            return None
    if "heute" in t or "today" in t or "stunde" in t or "hour" in t or "minute" in t:
        return today.isoformat()
    if "gestern" in t or "yesterday" in t:
        return (today - timedelta(days=1)).isoformat()
    for regex in (_GERMAN_RELATIVE, _EN_RELATIVE):
        m = regex.search(t)
        if m:
            n_raw = m.group(1)
            n = int(n_raw) if n_raw.isdigit() else 1
            unit = m.group(2)
            days = 1
            if unit.startswith(("woche", "week")):
                days = 7
            elif unit.startswith(("monat", "month")):
                days = 30
            elif unit.startswith(("stunde", "hour")):
                days = 0
            return (today - timedelta(days=n * days)).isoformat()
    return None


def iso_date(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO datetime/date string to YYYY-MM-DD."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        m = re.match(r"\d{4}-\d{2}-\d{2}", value)
        return m.group(0) if m else None
