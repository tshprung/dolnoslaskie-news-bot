import sqlite3
import time

from database import get_new_articles, normalize_article_url, record_seen_url


def test_normalize_article_url_strips_query_and_www():
    u = "https://www.zeit.de/path/to/story?utm_source=x"
    assert normalize_article_url(u) == "https://zeit.de/path/to/story"


def test_record_seen_url_blocks_second_id_same_link(monkeypatch):
    """Same canonical URL with different RSS ids → only first ingest."""

    def fake_parse(_url):
        class F:
            title = "Test"

        f = F()
        f.feed = {"title": "T"}
        now = time.gmtime()
        f.entries = [
            {
                "id": "tag:zeit:1",
                "link": "https://www.zeit.de/news/2026/el-nino",
                "title": "El Niño A",
                "summary": "A",
                "published_parsed": now,
            },
            {
                "id": "tag:zeit:2",
                "link": "https://zeit.de/news/2026/el-nino/",
                "title": "El Niño B",
                "summary": "B",
                "published_parsed": now,
            },
        ]
        return f

    monkeypatch.setattr("database.feedparser.parse", fake_parse)
    monkeypatch.setattr("database.FEEDS", ["http://fake.local/feed"])

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE seen_articles (id TEXT PRIMARY KEY, "
        "sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE dedup_recent ("
        "article_id TEXT PRIMARY KEY, title TEXT NOT NULL, "
        "summary TEXT NOT NULL, sort_epoch INTEGER NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE seen_article_urls (url_norm TEXT PRIMARY KEY, "
        "seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE age_skipped_urls (url_norm TEXT PRIMARY KEY, "
        "skipped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )

    first = get_new_articles(conn)
    assert len(first) == 1
    assert first[0]["id"] == "tag:zeit:1"

    record_seen_url(conn, first[0]["url_norm"])
    conn.commit()

    second = get_new_articles(conn)
    assert len(second) == 0
