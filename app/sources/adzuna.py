"""Adzuna — job aggregator with an official API (free key at developer.adzuna.com).

The API only returns a snippet of each description, so these jobs are analysed from
the snippet unless the same job was also found on karriere.at or LinkedIn.
"""
from __future__ import annotations

from typing import AsyncIterator, List, Optional
from urllib.parse import urlencode

from .base import AuthRequired, JobSource, PoliteClient, RawJob, SourceError, clean, html_to_text, iso_date

API = "https://api.adzuna.com/v1/api/jobs/at/search/{page}"
PAGE_SIZE = 50


def parse_results(payload: dict) -> List[RawJob]:
    jobs = []
    for r in payload.get("results") or []:
        if not r.get("id"):
            continue
        salary = None
        if r.get("salary_min") and not r.get("salary_is_predicted") in (1, "1"):
            lo, hi = r.get("salary_min"), r.get("salary_max")
            salary = f"{int(lo):,} – {int(hi):,} € / Jahr".replace(",", ".") if hi and hi != lo else f"ab {int(lo):,} € / Jahr".replace(",", ".")
        employment = ", ".join(x for x in [r.get("contract_time"), r.get("contract_type")] if x) or None
        jobs.append(
            RawJob(
                source="adzuna",
                source_id=str(r["id"]),
                url=r.get("redirect_url") or "",
                title=clean(html_to_text(r.get("title"))) or "",
                company=clean((r.get("company") or {}).get("display_name")),
                location=clean((r.get("location") or {}).get("display_name")),
                posted_at=iso_date(r.get("created")),
                description=clean(html_to_text(r.get("description"))),
                description_is_full=False,
                employment_raw=employment,
                salary_text=salary,
            )
        )
    return jobs


class AdzunaSource(JobSource):
    key = "adzuna"
    supports_detail = False

    def __init__(self, app_id: Optional[str], app_key: Optional[str], max_days_old: int = 30):
        if not app_id or not app_key:
            raise AuthRequired("Adzuna needs an App ID and App Key (free at developer.adzuna.com). Add them in Settings.")
        self.app_id, self.app_key, self.max_days_old = app_id, app_key, max_days_old
        self.http = PoliteClient(min_interval=1.0, headers={"Accept": "application/json"})

    async def search(self, keyword: str, max_pages: int) -> AsyncIterator[List[RawJob]]:
        for page in range(1, max_pages + 1):
            params = {
                "app_id": self.app_id,
                "app_key": self.app_key,
                "what": keyword,
                "results_per_page": PAGE_SIZE,
                "content-type": "application/json",
            }
            if self.max_days_old > 0:
                params["max_days_old"] = self.max_days_old
            resp = await self.http.get(API.format(page=page) + "?" + urlencode(params))
            if resp.status_code in (401, 403):
                raise AuthRequired("Adzuna rejected the App ID / App Key. Check them in Settings.")
            if resp.status_code != 200:
                raise SourceError(f"Adzuna returned HTTP {resp.status_code}: {resp.text[:200]}")
            jobs = parse_results(resp.json())
            yield jobs
            if len(jobs) < PAGE_SIZE:
                break

    async def aclose(self) -> None:
        await self.http.aclose()
