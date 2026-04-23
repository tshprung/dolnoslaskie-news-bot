from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import database as db
from database import init_db, normalize_article_url


def test_echo24_scrape_skips_old_publish_dates(monkeypatch, tmp_path: Path):
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    conn = init_db()

    monkeypatch.setattr(
        db,
        "SCRAPE_SOURCES",
        [{"key": "echo24", "list_url": "https://echo24.tv/"}],
    )
    monkeypatch.setattr(db, "SCRAPE_SOURCES_MIN_INTERVAL_SEC", 0)

    listing_html = """
    <html><body>
      <a href="/pl/11_wiadomosci/93512_w-muzeum-etnograficznym-wystawa-pisanek-i-palm-wielkanocnych.html">
        Wystawa pisanek
      </a>
      <a href="/pl/11_wiadomosci/94686_wroclawskie-kamienice.html">
        Wrocławskie kamienice nie do poznania
      </a>
    </body></html>
    """

    monkeypatch.setattr(db, "fetch_listing_html", lambda *_a, **_k: listing_html)

    now = datetime(2026, 4, 22, 9, 20, tzinfo=timezone.utc)

    def fake_pub(_session, url: str, _timeout):
        if "93512" in url:
            return now - timedelta(days=40)
        if "94686" in url:
            return now - timedelta(hours=2)
        return None

    monkeypatch.setattr(db, "echo24_fetch_published_utc", fake_pub)

    session = MagicMock()
    scraped = db._scrape_listing_sources(conn, session, (1, 2), now, set())
    assert len(scraped) == 1
    assert "94686" in scraped[0]["link"]

    stale_norm = normalize_article_url(
        "https://echo24.tv/pl/11_wiadomosci/93512_w-muzeum-etnograficznym-wystawa-pisanek-i-palm-wielkanocnych.html"
    )
    row = conn.execute(
        "SELECT 1 FROM seen_article_urls WHERE url_norm = ?", (stale_norm,)
    ).fetchone()
    assert row is not None


def test_echo24_extract_published_time_from_meta():
    from scrape_sources import echo24_extract_published_utc_from_html

    html = """
    <html><head>
      <meta property="article:published_time" content="2026-03-14T14:40:18+01:00" />
    </head></html>
    """
    dt = echo24_extract_published_utc_from_html(html)
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 3
