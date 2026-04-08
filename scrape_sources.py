"""Scrape non-RSS listing pages into RSS-like entries (Dolnośląsk bot)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
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

