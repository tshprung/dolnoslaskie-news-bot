"""Scrape non-RSS listing pages into RSS-like entries (Dolnośląsk bot)."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, urlunparse
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger(__name__)


def _strip_query_and_fragment(url: str) -> str:
    p = urlparse((url or "").strip())
    if not p.netloc:
        return url
    scheme = (p.scheme or "https").lower()
    netloc = p.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = p.path or ""
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return urlunparse((scheme, netloc, path, "", "", ""))


def fetch_listing_html(session: requests.Session, url: str, timeout: tuple) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
    }
    resp = session.get(url, timeout=timeout, headers=headers)
    resp.raise_for_status()
    return resp.text or ""


_PL_MONTH = {
    "stycznia": 1,
    "lutego": 2,
    "marca": 3,
    "kwietnia": 4,
    "maja": 5,
    "czerwca": 6,
    "lipca": 7,
    "sierpnia": 8,
    "września": 9,
    "wrzesnia": 9,
    "października": 10,
    "pazdziernika": 10,
    "listopada": 11,
    "grudnia": 12,
}


def _dt_to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_iso_datetime_to_utc(s: str) -> datetime | None:
    raw = (s or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except Exception:
        return None
    return _dt_to_utc(dt)


def parse_rss_datetime_string(s: str) -> datetime | None:
    """
    Parse RSS/Atom date strings when feedparser leaves published_parsed empty
    (common on portalsamorzadowy.pl: RFC822 without timezone).
    """
    raw = (s or "").strip()
    if not raw:
        return None
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(raw)
    except Exception:
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("Europe/Warsaw"))
    return dt.astimezone(timezone.utc)


def rss_entry_published_utc(entry) -> datetime | None:
    """Original publish time from an RSS/Atom entry (never updated/modified)."""
    published = entry.get("published_parsed")
    if published:
        return datetime(*published[:6], tzinfo=timezone.utc)
    for key in ("published", "pubDate"):
        raw = entry.get(key)
        if not raw and hasattr(entry, key):
            raw = getattr(entry, key, None)
        if raw:
            dt = parse_rss_datetime_string(str(raw))
            if dt is not None:
                return dt
    return None


_ARTICLE_JSONLD_TYPES = frozenset(
    {"NewsArticle", "Article", "BlogPosting", "ReportageNewsArticle"}
)


def _jsonld_article_types(obj: dict) -> list[str]:
    t = obj.get("@type")
    if isinstance(t, str):
        return [t]
    if isinstance(t, list):
        return [x for x in t if isinstance(x, str)]
    return []


def _jsonld_iter_objects(obj):
    if obj is None:
        return
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _jsonld_iter_objects(v)
        return
    if isinstance(obj, list):
        for it in obj:
            yield from _jsonld_iter_objects(it)
        return


def html_extract_first_publish_utc_from_html(html: str) -> datetime | None:
    h = html or ""

    for m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        h,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        raw = (m.group(1) or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        for o in _jsonld_iter_objects(data):
            if not isinstance(o, dict):
                continue
            if not any(t in _ARTICLE_JSONLD_TYPES for t in _jsonld_article_types(o)):
                continue
            dp = o.get("datePublished")
            if isinstance(dp, str):
                dt = _parse_iso_datetime_to_utc(dp)
                if dt is not None:
                    return dt

    for m in re.finditer(
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
        h,
        flags=re.IGNORECASE,
    ):
        dt = _parse_iso_datetime_to_utc(m.group(1))
        if dt is not None:
            return dt

    for m in re.finditer(
        r'<meta[^>]+name=["\'](?:pubdate|publish-date|date|dc\.date|dc\.date\.issued)["\'][^>]+content=["\']([^"\']+)["\']',
        h,
        flags=re.IGNORECASE,
    ):
        dt = _parse_iso_datetime_to_utc(m.group(1))
        if dt is not None:
            return dt

    for m in re.finditer(
        r"<time[^>]+datetime=['\"]([^'\"]+)['\"]",
        h,
        flags=re.IGNORECASE,
    ):
        dt = _parse_iso_datetime_to_utc(m.group(1))
        if dt is not None:
            return dt

    m = re.search(
        r"Opublikowano:\s*(\d{1,2})\s+([a-ząćęłńóśźż]+)\s+(\d{4})\s*(?:[-–]\s*(\d{1,2}):(\d{2}))?",
        h,
        flags=re.IGNORECASE,
    )
    if m:
        day = int(m.group(1))
        month_name = (m.group(2) or "").strip().lower()
        year = int(m.group(3))
        hour = int(m.group(4) or "0")
        minute = int(m.group(5) or "0")
        month = _PL_MONTH.get(month_name)
        if month:
            try:
                local = datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("Europe/Warsaw"))
                return local.astimezone(timezone.utc)
            except Exception:
                return None

    return None


def echo24_extract_published_utc_from_html(html: str) -> datetime | None:
    return html_extract_first_publish_utc_from_html(html)



@dataclass(frozen=True)
class ListingItem:
    url: str
    title: str


def extract_24wroclaw_items(listing_html: str, base_url: str = "https://24wroclaw.pl/") -> list[ListingItem]:
    """
    Extract (url, title) pairs from https://24wroclaw.pl/wiadomosci/.
    Prefer DOM parsing; fall back to regex if bs4 is unavailable.
    """
    html = listing_html or ""
    out: list[ListingItem] = []
    seen: set[str] = set()

    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a[href]"):
            href = (a.get("href") or "").strip()
            if not href:
                continue
            if "/artykul/" not in href:
                continue
            title = a.get_text(" ", strip=True)
            if not title or len(title) < 12:
                continue
            url = urljoin(base_url, href)
            url = _strip_query_and_fragment(url)
            if url in seen:
                continue
            seen.add(url)
            out.append(ListingItem(url=url, title=title))
        return out
    except Exception:
        pass

    # Regex fallback: pick hrefs to /artykul/ and use surrounding text heuristics.
    for m in re.finditer(r'href=["\']([^"\']*/artykul/[^"\']+)["\']', html, flags=re.IGNORECASE):
        href = m.group(1).strip()
        url = _strip_query_and_fragment(urljoin(base_url, href))
        if url in seen:
            continue
        seen.add(url)
        out.append(ListingItem(url=url, title=""))  # title may be filled later by fetcher
    return out


def extract_echo24_items(listing_html: str, base_url: str = "https://echo24.tv/") -> list[ListingItem]:
    """
    Extract (url, title) pairs from https://echo24.tv/ (homepage).
    Target news URLs under /pl/11_wiadomosci/<id>_...html.
    """
    html = listing_html or ""
    out: list[ListingItem] = []
    seen: set[str] = set()
    pat_rel = re.compile(r"^/pl/11_wiadomosci/\d+_[^?#]+\.html$", re.IGNORECASE)
    pat_abs = re.compile(
        r"^https?://(?:www\.)?echo24\.tv/pl/11_wiadomosci/\d+_[^?#]+\.html$",
        re.IGNORECASE,
    )

    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a[href]"):
            href = (a.get("href") or "").strip()
            if not href:
                continue
            href_norm = _strip_query_and_fragment(urljoin(base_url, href))
            if not (pat_rel.match(href) or pat_abs.match(href_norm)):
                continue
            title = a.get_text(" ", strip=True)
            if not title or len(title) < 10:
                continue
            url = href_norm
            if url in seen:
                continue
            seen.add(url)
            out.append(ListingItem(url=url, title=title))
        return out
    except Exception:
        pass

    for m in re.finditer(r'href=["\'](/pl/11_wiadomosci/\d+_[^"\']+?\.html)["\']', html, flags=re.IGNORECASE):
        href = m.group(1).strip()
        url = _strip_query_and_fragment(urljoin(base_url, href))
        if url in seen:
            continue
        seen.add(url)
        out.append(ListingItem(url=url, title=""))
    return out


_ARTYKUL_ID_RE = re.compile(
    r"^/artykul/(\d+)(?:/k/\d+)?(?:/([^/?#]+))?$",
    re.IGNORECASE,
)


def canonical_walbrzych24_article_url(url: str) -> str:
    """
    Collapse /artykul/{id}/k/{n}/{slug} variants to /artykul/{id}/{slug} for stable dedup.
    """
    raw = _strip_query_and_fragment((url or "").strip())
    p = urlparse(raw)
    m = _ARTYKUL_ID_RE.match(p.path or "")
    if not m:
        return raw
    article_id, slug = m.group(1), m.group(2)
    path = f"/artykul/{article_id}/{slug}" if slug else f"/artykul/{article_id}"
    scheme = (p.scheme or "https").lower()
    netloc = (p.netloc or "").lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return urlunparse((scheme, netloc, path, "", "", ""))


def extract_walbrzych24_items(
    listing_html: str, base_url: str = "https://www.walbrzych24.com/"
) -> list[ListingItem]:
    """
    Extract (url, title) from https://www.walbrzych24.com/ (Wałbrzych local news).
    """
    html = listing_html or ""
    out: list[ListingItem] = []
    seen: set[str] = set()

    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a[href]"):
            href = (a.get("href") or "").strip()
            if not href or "/artykul/" not in href:
                continue
            title = a.get_text(" ", strip=True)
            if not title or len(title) < 12:
                continue
            url = canonical_walbrzych24_article_url(urljoin(base_url, href))
            p = urlparse(url)
            if not _ARTYKUL_ID_RE.match(p.path or ""):
                continue
            if url in seen:
                continue
            seen.add(url)
            out.append(ListingItem(url=url, title=title))
        return out
    except Exception:
        pass

    for m in re.finditer(
        r'href=["\']([^"\']*/artykul/\d+[^"\']*)["\']',
        html,
        flags=re.IGNORECASE,
    ):
        url = canonical_walbrzych24_article_url(urljoin(base_url, m.group(1).strip()))
        if url in seen:
            continue
        p = urlparse(url)
        if not _ARTYKUL_ID_RE.match(p.path or ""):
            continue
        seen.add(url)
        out.append(ListingItem(url=url, title=""))
    return out
