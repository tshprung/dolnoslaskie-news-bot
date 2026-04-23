"""Scrape non-RSS listing pages into RSS-like entries (Dolnośląsk bot)."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, urlunparse

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


def _parse_iso_datetime_to_utc(value: str) -> datetime | None:
    s = (value or "").strip()
    if not s:
        return None
    # feedparser-style / HTML datetime often ends with Z
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def html_extract_first_publish_utc_from_html(page_html: str) -> datetime | None:
    """
    Best-effort *first publish* time from article HTML.

    Prefer `article:published_time` and JSON-LD `datePublished`.
    Optionally fall back to `og:updated_time` / `dateModified` only if nothing else exists
    (some sites omit published_time entirely).
    """
    html = page_html or ""
    if not html.strip():
        return None

    # OpenGraph / article meta (published first)
    for pat in (
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']article:published_time["\']',
    ):
        m = re.search(pat, html, flags=re.IGNORECASE)
        if m:
            dt = _parse_iso_datetime_to_utc(m.group(1))
            if dt:
                return dt

    # JSON-LD (prefer datePublished; only use dateModified if no datePublished exists)
    for m in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    ):
        raw = (m.group(1) or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        candidates = []
        if isinstance(data, dict):
            g = data.get("@graph")
            if isinstance(g, list):
                candidates = [x for x in g if isinstance(x, dict)]
            else:
                candidates = [data]
        elif isinstance(data, list):
            candidates = [x for x in data if isinstance(x, dict)]

        best_pub: datetime | None = None
        best_any: datetime | None = None
        for item in candidates:
            if not isinstance(item, dict):
                continue
            t = item.get("@type")
            types = [t] if isinstance(t, str) else ([x for x in t if isinstance(x, str)] if isinstance(t, list) else [])
            if types and not any(x in ("NewsArticle", "Article", "WebPage") for x in types):
                continue
            dp = item.get("datePublished")
            if isinstance(dp, str):
                dt = _parse_iso_datetime_to_utc(dp)
                if dt and (best_pub is None or dt < best_pub):
                    best_pub = dt
            dm = item.get("dateModified")
            if isinstance(dm, str):
                dt = _parse_iso_datetime_to_utc(dm)
                if dt and (best_any is None or dt < best_any):
                    best_any = dt
        if best_pub:
            return best_pub
        if best_any:
            return best_any

    # Last-resort meta fallbacks
    for pat in (
        r'<meta[^>]+property=["\']og:updated_time["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:updated_time["\']',
    ):
        m = re.search(pat, html, flags=re.IGNORECASE)
        if m:
            dt = _parse_iso_datetime_to_utc(m.group(1))
            if dt:
                return dt

    return None


def echo24_extract_published_utc_from_html(page_html: str) -> datetime | None:
    """Back-compat alias (echo24 uses the same HTML signals as most outlets)."""
    return html_extract_first_publish_utc_from_html(page_html)


def echo24_fetch_published_utc(session: requests.Session, url: str, timeout: tuple) -> datetime | None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
    }
    try:
        resp = session.get(url, timeout=timeout, headers=headers)
        resp.raise_for_status()
        return html_extract_first_publish_utc_from_html(resp.text or "")
    except Exception as e:
        log.info("echo24: could not fetch/parse publish time for %s (%s)", url, e)
        return None


def article_html_fetch_published_utc(session: requests.Session, url: str, timeout: tuple) -> datetime | None:
    """Fetch arbitrary article HTML and extract a best-effort first-publish timestamp."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
    }
    try:
        resp = session.get(url, timeout=timeout, headers=headers)
        resp.raise_for_status()
        return html_extract_first_publish_utc_from_html(resp.text or "")
    except Exception as e:
        log.info("article html: could not fetch/parse publish time for %s (%s)", url, e)
        return None


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
    seen: set[str] = set()
    pat_rel = re.compile(r"^/pl/11_wiadomosci/\d+_[^?#]+\.html$", re.IGNORECASE)
    pat_abs = re.compile(
        r"^https?://(?:www\.)?echo24\.tv/pl/11_wiadomosci/\d+_[^?#]+\.html$",
        re.IGNORECASE,
    )
    id_re = re.compile(r"/pl/11_wiadomosci/(\d+)_", re.IGNORECASE)

    def echo24_story_id(url: str) -> int | None:
        m = id_re.search(url or "")
        if not m:
            return None
        try:
            return int(m.group(1))
        except ValueError:
            return None

    def split_echo24_homepage_sections(raw: str) -> tuple[str, str]:
        """
        echo24 homepage mixes fresh "Aktualności" with long-lived accident digests under a
        "Wypadki" block. The digests often contain months-old /11_wiadomosci/ IDs that are not
        "new news", but they still match our URL pattern — split so we can apply stricter gates.
        """
        low = (raw or "").lower()
        # Prefer the accidents/regional digest heading if present.
        for needle in (
            "wypadki",
            "na sygnale",
        ):
            i = low.find(needle)
            if i != -1:
                return raw[:i], raw[i:]
        return raw, ""

    def filter_echo24_candidates(tagged: list[tuple[ListingItem, str]]) -> list[ListingItem]:
        if not tagged:
            return []
        pre_html, post_html = split_echo24_homepage_sections(html)

        def max_id_in_html(blob: str) -> int | None:
            ids = [int(m.group(1)) for m in id_re.finditer(blob or "")]
            return max(ids) if ids else None

        max_pre = max_id_in_html(pre_html) or 0
        max_post = max_id_in_html(post_html) or 0
        if not max_pre:
            max_pre = max(
                (echo24_story_id(it.url) or 0 for it, sec in tagged if sec == "pre"),
                default=0,
            )

        # Primary gate: ignore very stale IDs compared to the newest ID seen above the digest area.
        # (echo24 IDs are monotonic enough for this to be a strong freshness signal.)
        min_pre_id = max(0, int(max_pre) - 2000)

        # Secondary gate: items that only appear in the digest/footer area must be near-current.
        digest_min_id = max(0, int(max_pre) - 800) if max_pre else 0

        kept: list[ListingItem] = []
        for it, sec in tagged:
            sid = echo24_story_id(it.url)
            if sid is None:
                continue

            if sec == "pre":
                if sid < min_pre_id:
                    continue
                kept.append(it)
                continue

            # Post-section: allow only if it looks like a genuinely fresh item (not an old digest).
            if max_post and sid >= max(int(max_post) - 300, digest_min_id):
                kept.append(it)
                continue

        return kept

    try:
        from bs4 import BeautifulSoup  # type: ignore

        pre_html, post_html = split_echo24_homepage_sections(html)
        tagged: list[tuple[ListingItem, str]] = []

        def parse_fragment(fragment: str, sec: str) -> None:
            if not (fragment or "").strip():
                return
            soup = BeautifulSoup(fragment, "html.parser")
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
                tagged.append((ListingItem(url=url, title=title), sec))

        parse_fragment(pre_html, "pre")
        parse_fragment(post_html, "post")
        return filter_echo24_candidates(tagged)
    except Exception:
        pass

    pre_html, post_html = split_echo24_homepage_sections(html)
    tagged: list[tuple[ListingItem, str]] = []
    for sec, frag in (("pre", pre_html), ("post", post_html)):
        if not (frag or "").strip():
            continue
        for m in re.finditer(r'href=["\'](/pl/11_wiadomosci/\d+_[^"\']+?\.html)["\']', frag, flags=re.IGNORECASE):
            href = m.group(1).strip()
            url = _strip_query_and_fragment(urljoin(base_url, href))
            if url in seen:
                continue
            seen.add(url)
            tagged.append((ListingItem(url=url, title=""), sec))
    return filter_echo24_candidates(tagged)

