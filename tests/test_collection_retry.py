import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
import requests

import database
import retry_queue


@pytest.fixture
def conn(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(database, "FEEDS", ["https://example.com/rss"])
    monkeypatch.setattr(database, "SCRAPE_SOURCES", [])
    db = database.init_db()
    yield db
    db.close()


def session_for_feed(published=True):
    date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    publication = f"<pubDate>{date}</pubDate>" if published else ""
    response = requests.Response()
    response.status_code = 200
    response._content = (
        '<rss version="2.0"><channel><title>Local news</title><item>'
        '<guid>story-1</guid><link>https://example.com/story</link>'
        f'<title>Wrocław water update</title>{publication}</item></channel></rss>'
    ).encode("utf-8")
    session = MagicMock()
    session.get.return_value = response
    return session


def test_rss_uses_http_session_timeout_and_parses_response_bytes(conn):
    session = session_for_feed()
    rows = database.get_new_articles(conn, session, (3, 7))
    session.get.assert_called_once_with("https://example.com/rss", timeout=(3, 7))
    assert [row['id'] for row in rows] == ['story-1']
    assert rows[0]['title'] == 'Wrocław water update'


def test_missing_date_is_retried_without_stale_or_seen_records(conn):
    session = session_for_feed(published=False)
    assert database.get_new_articles(conn, session, (1, 2)) == []
    assert conn.execute("SELECT count(*) FROM age_skipped_urls").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM seen_article_urls").fetchone()[0] == 0
    assert conn.execute("SELECT attempts FROM article_retries").fetchone()[0] == 1
    # The feed is still polled, but the individual article is not attempted again yet.
    database.get_new_articles(conn, session, (1, 2))
    assert conn.execute("SELECT attempts FROM article_retries").fetchone()[0] == 1
    conn.execute("UPDATE article_retries SET next_epoch=0")
    recovered = database.get_new_articles(conn, session_for_feed(), (1, 2))
    assert len(recovered) == 1


def test_publication_date_retries_are_bounded(conn):
    session = session_for_feed(published=False)
    for _ in range(5):
        conn.execute("UPDATE article_retries SET next_epoch=0")
        database.get_new_articles(conn, session, (1, 2))
    assert conn.execute("SELECT attempts FROM article_retries").fetchone()[0] == retry_queue.MAX_ATTEMPTS
    assert not retry_queue.retry_due(conn, "https://example.com/story")
    assert conn.execute("SELECT count(*) FROM age_skipped_urls").fetchone()[0] == 0


def test_scraped_date_recovers_after_transient_failure(conn, monkeypatch):
    monkeypatch.setattr(database, "SCRAPE_SOURCES", [{"key": "24wroclaw", "list_url": "https://24wroclaw.pl/wiadomosci/"}])
    monkeypatch.setattr(database, "SCRAPE_SOURCES_MIN_INTERVAL_SEC", 0)
    monkeypatch.setattr(database, "fetch_listing_html", lambda *_a: '<a href="/artykul/123">Wrocław water supply update</a>')
    publication = MagicMock(return_value=None)
    monkeypatch.setattr(database, "article_html_fetch_published_utc", publication)
    now = datetime.now(timezone.utc)
    assert database._scrape_listing_sources(conn, MagicMock(), (1, 2), now, set()) == []
    assert conn.execute("SELECT count(*) FROM age_skipped_urls").fetchone()[0] == 0
    publication.return_value = now
    # Backoff prevents repeated fetches until it is due.
    assert database._scrape_listing_sources(conn, MagicMock(), (1, 2), now, set()) == []
    assert publication.call_count == 1
    conn.execute("UPDATE article_retries SET next_epoch=0")
    recovered = database._scrape_listing_sources(conn, MagicMock(), (1, 2), now, set())
    assert len(recovered) == 1


def test_feed_http_error_is_reported_and_not_parsed(conn, monkeypatch, caplog):
    session = MagicMock()
    session.get.side_effect = requests.Timeout("read timed out")
    parse = MagicMock()
    monkeypatch.setattr(database.feedparser, "parse", parse)
    assert database.get_new_articles(conn, session, (1, 2)) == []
    parse.assert_not_called()
    assert "Failed to fetch https://example.com/rss" in caplog.text


def test_http_retries_cannot_replay_telegram_posts():
    from http_util import make_http_session
    session = make_http_session()
    retry = session.get_adapter("https://").max_retries
    assert 'GET' in retry.allowed_methods
    assert 'POST' not in retry.allowed_methods
    session.close()


def test_stale_article_recording_releases_writer_lock_before_more_fetches(conn):
    database._mark_stale_rss_item(conn, 'old', 'https://example.com/old')
    assert not conn.in_transaction
    assert conn.execute("SELECT id FROM seen_articles").fetchone()[0] == 'old'
