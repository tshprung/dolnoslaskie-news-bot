"""Persistent source health and unique candidate outcomes; never stores secrets."""
import json
import logging
import time

log = logging.getLogger(__name__)


def init_metrics(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS source_checks (source TEXT, checked_at INTEGER, details TEXT)')
    conn.execute('CREATE INDEX IF NOT EXISTS source_checks_time ON source_checks(checked_at)')
    conn.execute('CREATE TABLE IF NOT EXISTS candidate_events (url TEXT,stage TEXT,source TEXT,reason TEXT,'
                 'created_at INTEGER,PRIMARY KEY(url,stage))')


def record_check(conn, source, **details):
    init_metrics(conn)
    now = int(time.time())
    with conn:
        conn.execute('INSERT INTO source_checks VALUES(?,?,?)', (source,now,json.dumps(details)))
        conn.execute('DELETE FROM source_checks WHERE checked_at < ?', (now-30*86400,))
    log.info('Source health: source=%s details=%s',source,json.dumps(details))


def source_due(conn, source):
    init_metrics(conn)
    row=conn.execute('SELECT checked_at,details FROM source_checks WHERE source=? ORDER BY checked_at DESC LIMIT 1',(source,)).fetchone()
    # Respect access denials and stop hammering an endpoint that blocks the VM.
    return not row or not (json.loads(row[1]).get('blocked') and row[0]>int(time.time())-86400)


def event(conn, article, stage, reason=''):
    init_metrics(conn)
    with conn:
        conn.execute('INSERT OR IGNORE INTO candidate_events VALUES(?,?,?,?,?)', (
            article.get('url_norm') or article.get('link') or article['id'],stage,
            article.get('_source_key') or article.get('source',''),reason[:500],int(time.time())))
