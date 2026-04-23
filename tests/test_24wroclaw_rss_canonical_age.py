from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import database as db
from database import get_new_articles, init_db, normalize_article_url


def test_24wroclaw_rss_respects_canonical_publish_time(monkeypatch, tmp_path: Path):
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    conn = init_db()

    monkeypatch.setattr(db, "FEEDS", ["https://example.com/dummy.xml"])
    monkeypatch.setattr(db, "SCRAPE_SOURCES", [])
    monkeypatch.setattr(db, "MAX_ARTICLE_AGE_HOURS", 24)

    now = datetime.now(timezone.utc)

    link = "https://24wroclaw.pl/artykul/nowa-aplikacja-nasz-wroclaw-n1810827"
    fake_pub = now - timedelta(days=8)

    entry = {
        "id": link,
        "link": link,
        "title": "Nowa aplikacja",
        "summary": "<p>Lead</p>",
        "published_parsed": now.timetuple(),
    }

    fake_feed = MagicMock()
    fake_feed.feed = {"title": "24wroclaw test"}
    fake_feed.entries = [entry]

    monkeypatch.setattr(db.feedparser, "parse", lambda *_a, **_k: fake_feed)

    def fake_canon(_session, url: str, _timeout):
        assert url == link
        return fake_pub

    monkeypatch.setattr(db, "article_html_fetch_published_utc", fake_canon)

    out = get_new_articles(conn, session=MagicMock(), timeout=(1, 2))
    assert out == []

    norm = normalize_article_url(link)
    row = conn.execute("SELECT 1 FROM seen_article_urls WHERE url_norm = ?", (norm,)).fetchone()
    assert row is not None


def test_html_extract_prefers_datepublished_over_datemodified():
    from scrape_sources import html_extract_first_publish_utc_from_html

    html = r"""
    <script type="application/ld+json">
    {"@type":"NewsArticle","headline":"x","datePublished":"2026-04-15T10:00:00+00:00","dateModified":"2026-04-22T10:00:00+00:00"}
    </script>
    """
    dt = html_extract_first_publish_utc_from_html(html)
    assert dt is not None
    assert dt.date().isoformat() == "2026-04-15"
