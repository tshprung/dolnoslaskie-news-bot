import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import digest


@pytest.fixture
def conn():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE bot_kv(k TEXT PRIMARY KEY,v TEXT NOT NULL)")
    digest.init_digest_db(db)
    yield db
    db.close()


def queue(conn, count=1, age_hours=0):
    now = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    for i in range(count):
        digest.store_digest_article(conn, {
            "id": str(i), "title": f"Report {i}", "link": f"https://example.com/{i}",
            "source": "Local source", "date": "today", "sort_key": now + timedelta(seconds=i),
        }, f"Useful factual summary for report {i}.")
    return digest._pending(conn)


def send(conn, **kwargs):
    digest.maybe_send_daily_digest(conn, kwargs.pop("client", MagicMock()), MagicMock(),
                                  (1, 2), "test-channel", kwargs.pop("dry_run", False), True, 0, 10)


def states(conn):
    return dict(conn.execute("SELECT id,status FROM digest_articles"))


def test_sent_history_contains_only_published_rows_and_unscanned_rows_stay_pending(conn, monkeypatch):
    rows = queue(conn, 61)
    monkeypatch.setattr(digest, "_select_and_rank", lambda *_a, **_k: [(rows[0], "Chosen story")])
    post = MagicMock()
    monkeypatch.setattr(digest, "send_to_telegram", post)
    send(conn)
    assert post.call_count == 1
    result = states(conn)
    assert result[rows[0][0]] == "published"
    assert result['0'] == "pending"  # outside the 60-row scan
    assert list(result.values()).count("excluded") == 59
    assert [row[0] for row in digest._recent_digest_history(conn)] == [rows[0][0]]
    assert conn.execute("SELECT count(*) FROM digest_articles WHERE digested_at IS NOT NULL").fetchone()[0] == 1
    send(conn)
    assert post.call_count == 1


def test_selected_story_removed_for_length_remains_pending(conn, monkeypatch):
    rows = queue(conn, 2)
    pairs = [(row, "Headline") for row in rows]
    monkeypatch.setattr(digest, "_select_and_rank", lambda *_a, **_k: pairs)
    monkeypatch.setattr(digest, "_fit_message", lambda _p: ("message", pairs[:1]))
    monkeypatch.setattr(digest, "send_to_telegram", MagicMock())
    send(conn)
    assert states(conn) == {rows[0][0]: "published", rows[1][0]: "pending"}


def test_delivery_failure_keeps_queue_and_does_not_seal_day(conn, monkeypatch):
    rows = queue(conn, 2)
    monkeypatch.setattr(digest, "_select_and_rank", lambda *_a, **_k: [(rows[0], "Headline")])
    post = MagicMock(side_effect=RuntimeError("Telegram unavailable"))
    monkeypatch.setattr(digest, "send_to_telegram", post)
    with pytest.raises(RuntimeError, match="Telegram unavailable"):
        send(conn)
    assert set(states(conn).values()) == {"pending"}
    assert conn.execute("SELECT count(*) FROM bot_kv").fetchone()[0] == 0
    post.side_effect = None
    send(conn)
    assert states(conn)[rows[0][0]] == "published"


def test_empty_editor_selection_is_valid_and_does_not_force_stories(conn, monkeypatch):
    queue(conn)
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"indices":[]}'))])
    post = MagicMock()
    monkeypatch.setattr(digest, "send_to_telegram", post)
    send(conn, client=client)
    post.assert_not_called()
    assert states(conn) == {"0": "excluded"}
    assert digest._recent_digest_history(conn) == []
    assert conn.execute("SELECT count(*) FROM bot_kv").fetchone()[0] == 0


def test_empty_queue_can_receive_a_digest_later_the_same_day(conn, monkeypatch):
    send(conn)
    rows = queue(conn)
    monkeypatch.setattr(digest, "_select_and_rank", lambda *_a, **_k: [(rows[0], "Headline")])
    post = MagicMock()
    monkeypatch.setattr(digest, "send_to_telegram", post)
    send(conn)
    post.assert_called_once()


def test_expiry_is_separate_from_publication(conn):
    queue(conn, age_hours=49)
    send(conn)
    assert states(conn) == {"0": "expired"}
    assert digest._recent_digest_history(conn) == []


def test_dry_run_does_not_change_article_or_delivery_state(conn, monkeypatch):
    rows = queue(conn, age_hours=49)
    monkeypatch.setattr(digest, "_select_and_rank", lambda *_a, **_k: [(rows[0], "Headline")])
    post = MagicMock()
    monkeypatch.setattr(digest, "send_to_telegram", post)
    send(conn, dry_run=True)
    assert states(conn) == {"0": "pending"}
    assert conn.execute("SELECT count(*) FROM bot_kv").fetchone()[0] == 0
    post.assert_not_called()


def test_schema_migration_is_idempotent_and_preserves_old_queue():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE digest_articles(id TEXT PRIMARY KEY,title TEXT,summary_en TEXT,url TEXT,"
               "source TEXT,article_date TEXT,sort_epoch INTEGER,queued_at TEXT,digested_at TEXT)")
    db.execute("INSERT INTO digest_articles(id,digested_at) VALUES('old','2026-10-20')")
    db.execute("INSERT INTO digest_articles(id,digested_at) VALUES('pending',NULL)")
    digest.init_digest_db(db)
    digest.init_digest_db(db)
    assert states(db) == {"old": "published", "pending": "pending"}
    db.close()


def test_html_expansion_still_fits_telegram_limit(conn):
    row = list(queue(conn)[0])
    row[2] = "&<>" * 3000
    message, pairs = digest._fit_message([(row, "Headline")])
    assert len(message) <= digest.TELEGRAM_SAFE_LIMIT
    assert pairs


def test_invalid_editor_json_uses_fallback_but_empty_array_does_not(conn):
    rows = queue(conn)
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='not JSON'))])
    assert digest._select_rows(client, rows, 10) == rows
