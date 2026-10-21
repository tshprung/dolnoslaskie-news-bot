"""Bounded retries for transient article failures, separate from stale/seen records."""
import logging
import time

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 30 * 60


def init_retry_db(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS article_retries ("
        "url_norm TEXT PRIMARY KEY, attempts INTEGER NOT NULL, "
        "next_epoch INTEGER NOT NULL, reason TEXT NOT NULL)"
    )


def retry_due(conn, url_norm):
    row = conn.execute(
        "SELECT attempts,next_epoch FROM article_retries WHERE url_norm=?", (url_norm,)
    ).fetchone()
    return not row or (row[0] < MAX_ATTEMPTS and row[1] <= int(time.time()))


def record_retry(conn, url_norm, reason):
    if not url_norm:
        return
    conn.execute(
        "INSERT INTO article_retries(url_norm,attempts,next_epoch,reason) VALUES(?,1,?,?) "
        "ON CONFLICT(url_norm) DO UPDATE SET "
        "attempts=article_retries.attempts+1, next_epoch=excluded.next_epoch, reason=excluded.reason",
        (url_norm, int(time.time()) + RETRY_DELAY_SECONDS, str(reason)[:500]),
    )
    conn.commit()
    attempts = conn.execute(
        "SELECT attempts FROM article_retries WHERE url_norm=?", (url_norm,)
    ).fetchone()[0]
    log.warning("Article retry: attempt=%d/%d exhausted=%s url=%s reason=%s",
                attempts, MAX_ATTEMPTS, attempts >= MAX_ATTEMPTS, url_norm, reason)


def clear_retry(conn, url_norm):
    conn.execute("DELETE FROM article_retries WHERE url_norm=?", (url_norm,))


def retryable_summary_failure(reason):
    return bool(reason and reason.startswith((
        "fetch failed", "fetch blocked", "no usable article text", "insufficient text",
    )))
