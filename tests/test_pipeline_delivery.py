import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

import database
import main


class InspectableConnection(sqlite3.Connection):
    def close(self):
        # main owns the connection; retain it for post-run assertions in tests.
        pass


@pytest.fixture
def conn(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    initial = database.init_db()
    initial.close()
    db = sqlite3.connect(database.DB_PATH, factory=InspectableConnection)
    monkeypatch.setattr(main, "init_db", lambda: db)
    monkeypatch.setattr(main, "make_http_session", MagicMock)
    monkeypatch.setattr(main, "openai_client", MagicMock)
    monkeypatch.setattr(main, "DRY_RUN", False)
    monkeypatch.setattr(main, "notify_admin", MagicMock())
    monkeypatch.setattr(main.time, "sleep", lambda _seconds: None)
    yield db
    sqlite3.Connection.close(db)


def article(aid='1', title='Wrocław: awaria wodociągu na ulicy Legnickiej', minutes=0):
    return dict(id=aid, title=title, summary='', link=f'https://example.com/{aid}',
                url_norm=f'https://example.com/{aid}', source='Local outlet', date='today',
                sort_key=datetime.now(timezone.utc) + timedelta(minutes=minutes))


def test_related_reports_reach_editor_with_latest_first(conn, monkeypatch):
    reports = [article(), article('2', 'Wrocław: usunięto awarię wodociągu na ulicy Legnickiej', 5)]
    monkeypatch.setattr(main, "get_new_articles", lambda *_a, **_k: reports)
    summarize = MagicMock(return_value=('Water supply has been restored in Wrocław.', None))
    monkeypatch.setattr(main, "summarize_in_english", summarize)
    deliver = MagicMock()
    monkeypatch.setattr(main, "_deliver_digest", deliver)
    main.main(mode='collect')
    assert [call.args[-1]['id'] for call in summarize.call_args_list] == ['2', '1']
    assert conn.execute("SELECT count(*) FROM digest_articles WHERE status='pending'").fetchone()[0] == 2
    deliver.assert_not_called()


def test_body_fetch_failure_stays_retryable_and_can_recover(conn, monkeypatch):
    report = article()
    monkeypatch.setattr(main, "get_new_articles", lambda *_a, **_k: [report])
    summarize = MagicMock(return_value=(None, 'fetch failed (HTTP 503): https://example.com/1'))
    monkeypatch.setattr(main, "summarize_in_english", summarize)
    main.main(mode='collect')
    assert conn.execute("SELECT count(*) FROM seen_articles").fetchone()[0] == 0
    assert conn.execute("SELECT attempts FROM article_retries").fetchone()[0] == 1
    summarize.return_value = ('A factual English report about Wrocław water supply.', None)
    main.main(mode='collect')
    assert conn.execute("SELECT count(*) FROM article_retries").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM seen_articles").fetchone()[0] == 1


def test_digest_mode_never_fetches_or_summarizes_articles(conn, monkeypatch):
    collect = MagicMock(side_effect=AssertionError('collection must not run'))
    monkeypatch.setattr(main, "get_new_articles", collect)
    deliver = MagicMock()
    monkeypatch.setattr(main, "_deliver_digest", deliver)
    main.main(mode='digest')
    deliver.assert_called_once()
    collect.assert_not_called()


def test_digest_errors_reach_scheduler(conn, monkeypatch):
    monkeypatch.setattr(main, "_deliver_digest", MagicMock(side_effect=RuntimeError('failed delivery')))
    with pytest.raises(RuntimeError, match='failed delivery'):
        main.main(mode='digest')
