"""Near-duplicate logic and cross-run snapshots."""
import sqlite3
from datetime import datetime, timedelta, timezone

from database import normalize_article_url
from dedup import (
    _is_near_duplicate,
    content_tokens,
    deduplicate,
    load_dedup_snapshots,
    record_sent_snapshot,
)


def _article(title, summary, aid, sort=None):
    if sort is None:
        sort = datetime.now(timezone.utc)
    link = f"https://ex.example/{aid}"
    return {
        "id": aid,
        "title": title,
        "summary": summary or "",
        "link": link,
        "url_norm": normalize_article_url(link),
        "source": "Test",
        "date": "",
        "sort_key": sort,
    }


def _memory_conn():
    c = sqlite3.connect(":memory:")
    c.execute(
        "CREATE TABLE seen_articles (id TEXT PRIMARY KEY, "
        "sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    c.execute(
        "CREATE TABLE dedup_recent ("
        "article_id TEXT PRIMARY KEY, title TEXT NOT NULL, "
        "summary TEXT NOT NULL, sort_epoch INTEGER NOT NULL)"
    )
    c.execute(
        "CREATE TABLE seen_article_urls (url_norm TEXT PRIMARY KEY, "
        "seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    return c


def test_politician_cluster_merges():
    w = timedelta(hours=8)
    a = _article(
        "Governo reage a críticas após entrevista do ministro",
        "Partido discute medidas em Lisboa após declarações.",
        "1",
    )
    b = _article(
        "Críticas da oposição após entrevista do ministro — Governo responde",
        "Debate político em Lisboa; ministro rejeita acusações.",
        "2",
    )
    dup, _ = _is_near_duplicate(a, b, w)
    assert dup is True


def test_accident_same_place_merges():
    w = timedelta(hours=8)
    a = _article(
        "Acidente com comboio corta circulação na Linha de Sintra",
        "Kurz.",
        "t1",
    )
    b = _article(
        "Atropelamento mortal interrompe circulação de comboios na Linha de Sintra",
        "Einsatz.",
        "t2",
    )
    dup, detail = _is_near_duplicate(a, b, w)
    assert dup is True


def test_cross_run_dedup_uses_snapshot():
    conn = _memory_conn()
    now = datetime.now(timezone.utc)
    prior = _article(
        "Incêndio em Lisboa encerra rua ao trânsito",
        "Bombeiros no local.",
        "sent-earlier",
        sort=now - timedelta(minutes=30),
    )
    record_sent_snapshot(conn, prior)
    conn.commit()

    incoming = _article(
        "Rua em Lisboa encerrada devido a incêndio",
        "Resumo diferente no RSS.",
        "new-id",
        sort=now,
    )
    kept = deduplicate(conn, [incoming])
    assert kept == []
    row = conn.execute("SELECT 1 FROM seen_articles WHERE id=?", (incoming["id"],)).fetchone()
    assert row is not None


def test_same_batch_first_wins():
    conn = _memory_conn()
    now = datetime.now(timezone.utc)
    a = _article("Gemeinsame tokens Headline", "Summary alpha beta gamma", "id-a", sort=now)
    b = _article("B Headline viele tokens", "Summary alpha beta delta", "id-b", sort=now)
    kept = deduplicate(conn, [a, b])
    assert len(kept) == 1
    assert kept[0]["id"] == "id-a"


def test_load_dedup_snapshots_respects_window():
    conn = _memory_conn()
    old = int((datetime.now(timezone.utc) - timedelta(hours=30)).timestamp())
    conn.execute(
        "INSERT INTO dedup_recent (article_id, title, summary, sort_epoch) VALUES (?,?,?,?)",
        ("old", "t", "s", old),
    )
    conn.commit()
    from config import DEDUP_WINDOW_HOURS

    rows = load_dedup_snapshots(conn, DEDUP_WINDOW_HOURS)
    ids = {r["id"] for r in rows}
    assert "old" not in ids


def test_english_dedup_catches_zoo_dodo_cross_source_nine_hours_apart():
    from dedup import is_english_near_duplicate, record_sent_en_snapshot

    conn = _memory_conn()
    conn.execute(
        "CREATE TABLE dedup_recent_en ("
        "article_id TEXT PRIMARY KEY, summary_en TEXT NOT NULL, sort_epoch INTEGER NOT NULL)"
    )
    t1 = datetime(2026, 6, 16, 9, 27, tzinfo=timezone.utc)
    t2 = datetime(2026, 6, 16, 18, 3, tzinfo=timezone.utc)
    en1 = (
        "Fundacja ZOO Wrocław – DODO, established by ZOO Wrocław in 2016, marks a decade of efforts "
        "to save endangered species worldwide. The foundation supports projects in Europe, Africa, and Asia."
    )
    en2 = (
        "The ZOO Wrocław Foundation – DODO marked its 10th anniversary, celebrating its efforts to "
        "support endangered animal populations globally across Europe, Africa, and Asia."
    )
    record_sent_en_snapshot(conn, "radio-161500", en1, t1)
    dup, detail = is_english_near_duplicate(conn, "wroclaw-dodo", en2, t2)
    assert dup is True
    assert detail
