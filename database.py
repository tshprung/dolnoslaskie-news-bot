"""SQLite: seen article ids + snapshots for cross-run dedup."""
import logging
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse
from zoneinfo import ZoneInfo

import feedparser

from config import (
    DB_PATH,
    DISPLAY_TZ,
    FEEDS,
    MAX_ARTICLE_AGE_HOURS,
    SCRAPE_SOURCES,
    SCRAPE_SOURCES_JITTER_MAX_SEC,
    SCRAPE_SOURCES_JITTER_MIN_SEC,
    SCRAPE_SOURCES_MAX_NEW_URLS,
    SCRAPE_SOURCES_MIN_INTERVAL_SEC,
)
from scrape_sources import (
    extract_24wroclaw_items,
    extract_echo24_items,
    fetch_listing_html,
)

log = logging.getLogger(__name__)

_DEDUP_RECENT_TTL_SEC = 48 * 3600
_SUMMARY_MAX_CHARS = 5000


def _entry_text_excerpt(entry) -> str:
    """Plain-text excerpt for classify/dedup; use content:encoded when summary is empty (common on ZEIT)."""
    raw = entry.get("summary") or ""
    stripped = re.sub(r"<[^>]+>", "", raw).strip()
    if len(stripped) >= 120:
        return stripped[:_SUMMARY_MAX_CHARS]

    content = entry.get("content") or []
    if isinstance(content, list) and content:
        val = content[0].get("value") or ""
        from_content = re.sub(r"<[^>]+>", " ", val)
        from_content = re.sub(r"\s+", " ", from_content).strip()
        low = from_content.lower()
        if low in ("none", "null") or (len(from_content) < 8 and low.startswith("none")):
            from_content = ""
        if len(from_content) > len(stripped):
            return from_content[:_SUMMARY_MAX_CHARS]
    return stripped[:_SUMMARY_MAX_CHARS]


def normalize_article_url(url: str) -> str:
    """Stable key for dedup: scheme+host+path, lowercase host, no query/fragment."""
    p = urlparse((url or "").strip())
    scheme = (p.scheme or "https").lower()
    netloc = (p.netloc or "").lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = p.path or ""
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return urlunparse((scheme, netloc, path, "", "", ""))


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS seen_articles "
        "(id TEXT PRIMARY KEY, sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS dedup_recent ("
        "article_id TEXT PRIMARY KEY, "
        "title TEXT NOT NULL, "
        "summary TEXT NOT NULL, "
        "sort_epoch INTEGER NOT NULL)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dedup_recent_epoch ON dedup_recent(sort_epoch)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS weekly_announce_sent ("
        "iso_week TEXT PRIMARY KEY, "
        "sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS seen_article_urls ("
        "url_norm TEXT PRIMARY KEY, "
        "seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS bot_kv ("
        "k TEXT PRIMARY KEY, "
        "v TEXT NOT NULL)"
    )
    conn.execute("DELETE FROM seen_articles WHERE sent_at < datetime('now', '-7 days')")
    conn.execute("DELETE FROM seen_article_urls WHERE seen_at < datetime('now', '-7 days')")
    cutoff = int(time.time()) - _DEDUP_RECENT_TTL_SEC
    conn.execute("DELETE FROM dedup_recent WHERE sort_epoch < ?", (cutoff,))
    conn.commit()
    return conn


def _kv_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT v FROM bot_kv WHERE k = ?", (key,)).fetchone()
    return row[0] if row else None


def _kv_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO bot_kv (k, v) VALUES (?, ?) "
        "ON CONFLICT(k) DO UPDATE SET v = excluded.v",
        (key, value),
    )


def record_seen_url(conn: sqlite3.Connection, url_norm: str) -> None:
    if not url_norm:
        return
    conn.execute(
        "INSERT OR IGNORE INTO seen_article_urls (url_norm) VALUES (?)",
        (url_norm,),
    )


def _scrape_listing_sources(
    conn: sqlite3.Connection,
    session,
    timeout: tuple,
    now_utc: datetime,
    urls_in_batch: set[str],
) -> list[dict]:
    """
    Scrape SCRAPE_SOURCES into RSS-like entries.
    Hourly-gated via bot_kv to avoid extra traffic when RSS runs more often.
    """
    import random
    import time as _time

    last_s = _kv_get(conn, "last_scrape_sources_epoch")
    last_epoch = int(last_s) if (last_s and last_s.isdigit()) else 0
    now_epoch = int(now_utc.timestamp())
    if now_epoch - last_epoch < int(SCRAPE_SOURCES_MIN_INTERVAL_SEC):
        return []

    scraped: list[dict] = []
    for i, src in enumerate(SCRAPE_SOURCES or []):
        key = (src or {}).get("key")
        list_url = (src or {}).get("list_url")
        if not key or not list_url:
            continue
        try:
            html = fetch_listing_html(session, list_url, timeout)
            if key == "24wroclaw":
                items = extract_24wroclaw_items(html, base_url=list_url)
            elif key == "echo24":
                items = extract_echo24_items(html, base_url=list_url)
            else:
                items = []
            for it in items:
                link = it.url
                if not link:
                    continue
                url_norm = normalize_article_url(link)
                if not url_norm or url_norm in urls_in_batch:
                    continue
                url_done = conn.execute(
                    "SELECT 1 FROM seen_article_urls WHERE url_norm = ?", (url_norm,)
                ).fetchone()
                if url_done:
                    continue
                urls_in_batch.add(url_norm)
                scraped.append(
                    {
                        "id": link,
                        "link": link,
                        "url_norm": url_norm,
                        "title": it.title or "",
                        "summary": "",
                        "source": key,
                        "date": now_utc.astimezone(ZoneInfo(DISPLAY_TZ)).strftime("%d.%m.%Y %H:%M"),
                        "sort_key": now_utc,
                    }
                )
                if len(scraped) >= int(SCRAPE_SOURCES_MAX_NEW_URLS):
                    break
            if len(scraped) >= int(SCRAPE_SOURCES_MAX_NEW_URLS):
                break
        except Exception as e:
            log.warning("Scrape source %s failed (%s): %s", key, list_url, e)
        # jitter between listing fetches
        if i < len(SCRAPE_SOURCES) - 1:
            jmin = float(SCRAPE_SOURCES_JITTER_MIN_SEC)
            jmax = float(SCRAPE_SOURCES_JITTER_MAX_SEC)
            if jmax < jmin:
                jmax = jmin
            _time.sleep(random.uniform(jmin, jmax))

    _kv_set(conn, "last_scrape_sources_epoch", str(now_epoch))
    conn.commit()
    return scraped


def get_new_articles(conn, session=None, timeout: tuple | None = None):
    """
    Returns new articles from RSS, plus hourly-gated SCRAPE_SOURCES listing scrapes if session+timeout provided.
    """
    new_articles = []
    tz = ZoneInfo(DISPLAY_TZ)
    urls_in_batch: set[str] = set()
    now_utc = datetime.now(timezone.utc)
    min_dt = now_utc - timedelta(hours=int(MAX_ARTICLE_AGE_HOURS))
    for feed_url in FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                article_id = entry.get("id") or entry.get("link")
                if not article_id:
                    continue
                link = entry.get("link") or article_id
                url_norm = normalize_article_url(link)
                exists = conn.execute(
                    "SELECT 1 FROM seen_articles WHERE id = ?", (article_id,)
                ).fetchone()
                url_done = conn.execute(
                    "SELECT 1 FROM seen_article_urls WHERE url_norm = ?", (url_norm,)
                ).fetchone()
                if exists or url_done or url_norm in urls_in_batch:
                    continue
                urls_in_batch.add(url_norm)
                published = entry.get("published_parsed")
                if published:
                    dt = datetime(*published[:6], tzinfo=timezone.utc)
                else:
                    dt = now_utc
                if dt < min_dt:
                    # Prevent old items from resurfacing on every run.
                    conn.execute(
                        "INSERT OR IGNORE INTO seen_articles (id) VALUES (?)", (article_id,)
                    )
                    record_seen_url(conn, url_norm)
                    continue
                dt_local = dt.astimezone(tz)
                new_articles.append(
                    {
                        "id": article_id,
                        "link": link,
                        "url_norm": url_norm,
                        "title": entry.get("title", ""),
                        "summary": _entry_text_excerpt(entry),
                        "source": feed.feed.get("title", feed_url),
                        "date": dt_local.strftime("%d.%m.%Y %H:%M"),
                        "sort_key": dt,
                    }
                )
        except Exception as e:
            log.error(f"Failed to fetch {feed_url}: {e}")

    # Non-RSS scrape sources (hourly gate).
    if session is not None and timeout is not None and SCRAPE_SOURCES:
        try:
            new_articles.extend(
                _scrape_listing_sources(conn, session, timeout, now_utc, urls_in_batch)
            )
        except Exception as e:
            log.warning("Scrape sources failed: %s", e)

    conn.commit()
    return new_articles
