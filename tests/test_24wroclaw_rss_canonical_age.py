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
    age_row = conn.execute("SELECT 1 FROM age_skipped_urls WHERE url_norm = ?", (norm,)).fetchone()
    assert age_row is not None


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


def test_html_extract_ignores_website_datemodified_without_article_publish():
    from scrape_sources import html_extract_first_publish_utc_from_html

    html = r"""
    <script type="application/ld+json">
    [
      {"@type":"WebSite","dateModified":"2026-06-16T19:20:00+02:00"},
      {"@type":"NewsArticle","headline":"x","datePublished":"2026-03-24T09:27:00+01:00","dateModified":"2026-03-24T09:27:35+01:00"}
    ]
    </script>
    """
    dt = html_extract_first_publish_utc_from_html(html)
    assert dt is not None
    assert dt.date().isoformat() == "2026-03-24"


def test_portalsamorzadowy_rss_string_skips_stale_without_published_parsed(monkeypatch, tmp_path: Path):
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    conn = init_db()

    monkeypatch.setattr(db, "FEEDS", ["https://example.com/dummy.xml"])
    monkeypatch.setattr(db, "SCRAPE_SOURCES", [])
    monkeypatch.setattr(db, "MAX_ARTICLE_AGE_HOURS", 24)

    now = datetime.now(timezone.utc)
    link = (
        "https://www.portalsamorzadowy.pl/dolnoslaskie/gospodarka-komunalna/"
        "miasto-rozdaje-darmowe-kompostowniki-mozna-oszczedzic-na-oplatach-za-smieci,653116.html"
    )
    entry = {
        "id": link,
        "link": link,
        "title": "Miasto rozdaje darmowe kompostowniki",
        "summary": "<p>Lead</p>",
        "published": "Tue, 24 Mar 2026 09:27:00",
        "published_parsed": None,
    }

    fake_feed = MagicMock()
    fake_feed.feed = {"title": "portalsamorzadowy test"}
    fake_feed.entries = [entry]

    monkeypatch.setattr(db.feedparser, "parse", lambda *_a, **_k: fake_feed)

    out = get_new_articles(conn, session=MagicMock(), timeout=(1, 2))
    assert out == []

    norm = normalize_article_url(link)
    row = conn.execute("SELECT 1 FROM seen_article_urls WHERE url_norm = ?", (norm,)).fetchone()
    assert row is not None
    age_row = conn.execute("SELECT 1 FROM age_skipped_urls WHERE url_norm = ?", (norm,)).fetchone()
    assert age_row is not None


def test_portalsamorzadowy_prusice_stawki_skips_stale(monkeypatch, tmp_path: Path):
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    conn = init_db()

    monkeypatch.setattr(db, "FEEDS", ["https://example.com/dummy.xml"])
    monkeypatch.setattr(db, "SCRAPE_SOURCES", [])
    monkeypatch.setattr(db, "MAX_ARTICLE_AGE_HOURS", 24)

    link = (
        "https://www.portalsamorzadowy.pl/dolnoslaskie/gospodarka-komunalna/"
        "stawki-coraz-czesciej-przekraczaja-50-zl-mieszkancy-zaplaca-az-40-proc-wiecej,651662.html"
    )
    entry = {
        "id": link,
        "link": link,
        "title": "Stawki coraz czesciej przekraczaja 50 zl",
        "summary": "<p>Lead</p>",
        "published": "Thu, 19 Mar 2026 15:25:00",
        "published_parsed": None,
    }

    fake_feed = MagicMock()
    fake_feed.feed = {"title": "portalsamorzadowy test"}
    fake_feed.entries = [entry]

    monkeypatch.setattr(db.feedparser, "parse", lambda *_a, **_k: fake_feed)

    out = get_new_articles(conn, session=MagicMock(), timeout=(1, 2))
    assert out == []

    norm = normalize_article_url(link)
    assert conn.execute("SELECT 1 FROM age_skipped_urls WHERE url_norm = ?", (norm,)).fetchone()


def test_portalsamorzadowy_wroclaw_smietniki_skips_stale(monkeypatch, tmp_path: Path):
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    conn = init_db()

    monkeypatch.setattr(db, "FEEDS", ["https://example.com/dummy.xml"])
    monkeypatch.setattr(db, "SCRAPE_SOURCES", [])
    monkeypatch.setattr(db, "MAX_ARTICLE_AGE_HOURS", 24)

    link = (
        "https://www.portalsamorzadowy.pl/dolnoslaskie/gospodarka-komunalna/"
        "skontrolowali-smietniki-w-centrum-miasta-mandaty-po-500-zl-i-zapowiedz-kolejnych-akcji,653316.html"
    )
    entry = {
        "id": link,
        "link": link,
        "title": "Skontrolowali smietniki w centrum miasta",
        "summary": "<p>Lead</p>",
        "published": "Tue, 17 Mar 2026 13:39:00",
        "published_parsed": None,
    }

    fake_feed = MagicMock()
    fake_feed.feed = {"title": "portalsamorzadowy test"}
    fake_feed.entries = [entry]

    monkeypatch.setattr(db.feedparser, "parse", lambda *_a, **_k: fake_feed)

    out = get_new_articles(conn, session=MagicMock(), timeout=(1, 2))
    assert out == []

    norm = normalize_article_url(link)
    assert conn.execute("SELECT 1 FROM age_skipped_urls WHERE url_norm = ?", (norm,)).fetchone()


def test_age_skipped_url_blocks_resurface_after_seen_expiry(monkeypatch, tmp_path: Path):
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    conn = init_db()

    monkeypatch.setattr(db, "FEEDS", ["https://example.com/dummy.xml"])
    monkeypatch.setattr(db, "SCRAPE_SOURCES", [])
    monkeypatch.setattr(db, "MAX_ARTICLE_AGE_HOURS", 24)

    link = "https://www.portalsamorzadowy.pl/dolnoslaskie/example,651662.html"
    entry = {
        "id": link,
        "link": link,
        "title": "Old",
        "summary": "x",
        "published": "Thu, 19 Mar 2026 15:25:00",
        "published_parsed": None,
    }
    fake_feed = MagicMock()
    fake_feed.feed = {"title": "psa"}
    fake_feed.entries = [entry]
    monkeypatch.setattr(db.feedparser, "parse", lambda *_a, **_k: fake_feed)

    norm = normalize_article_url(link)
    db.record_age_skipped_url(conn, norm)
    conn.commit()

    out = get_new_articles(conn, session=MagicMock(), timeout=(1, 2))
    assert out == []
