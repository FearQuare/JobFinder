"""Protection for a web app that only listens on localhost.

Binding to 127.0.0.1 keeps other machines out, but every website open in your browser can still send
requests to the app. These checks close that gap:

- Host allowlist: a DNS-rebinding page (evil.example resolving to 127.0.0.1) arrives with its own Host header.
- Same-origin writes: a cross-site form or fetch carries a foreign Origin / Sec-Fetch-Site header.
- Response headers: no framing, no MIME sniffing, scripts only from this app.

The module also renders untrusted text safely: scraped job URLs and AI-written Markdown.
"""
from __future__ import annotations

import html
from typing import Optional
from urllib.parse import urlsplit

import markdown as md
from fastapi import Request
from fastapi.responses import PlainTextResponse, Response

from . import config

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",   # style="width: …" on bars and progress
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "object-src 'none'",
])

SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    # Not "no-referrer": with that policy browsers send `Origin: null` on the app's own POSTs, which the
    # same-origin check below would refuse. "same-origin" still sends nothing to other sites.
    "Referrer-Policy": "same-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def _hostname(value: str) -> str:
    try:
        return (urlsplit("//" + value).hostname or "").lower()
    except ValueError:
        return ""


def host_allowed(host_header: str) -> bool:
    return _hostname(host_header) in config.ALLOWED_HOSTS


def same_origin_write(request: Request) -> bool:
    """True if a state-changing request comes from this app's own pages (or from a non-browser client)."""
    # Modern browsers say where a request comes from; this can't be set by page scripts.
    fetch_site = request.headers.get("sec-fetch-site", "")
    if fetch_site in ("cross-site", "same-site"):
        return False
    if fetch_site == "same-origin":
        return True
    origin = request.headers.get("origin")
    if origin is None:
        return True  # curl, tests and very old browsers send no Origin
    if origin == "null":
        return False  # sandboxed iframes and some redirects; never one of our pages
    return _hostname(urlsplit(origin).netloc) in config.ALLOWED_HOSTS


async def guard(request: Request, call_next) -> Response:
    if not host_allowed(request.headers.get("host", "")):
        return PlainTextResponse("Unknown host. Open JobFinder at http://127.0.0.1:8765", status_code=400)
    if request.method not in SAFE_METHODS and not same_origin_write(request):
        return PlainTextResponse("Cross-site request refused.", status_code=403)
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


def safe_url(url: Optional[str]) -> str:
    """Only http(s) links get rendered as links; anything else (javascript:, data:, …) becomes '#'."""
    url = (url or "").strip()
    try:
        scheme = urlsplit(url).scheme.lower()
    except ValueError:
        return "#"
    return url if scheme in ("http", "https") else "#"


def render_markdown(text: Optional[str]) -> str:
    """Markdown from the AI, with any raw HTML in it shown as text instead of being run by the browser."""
    return md.markdown(html.escape(text or "", quote=False), extensions=["sane_lists"])
