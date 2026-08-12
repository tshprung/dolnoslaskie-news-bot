"""Daily digest storage and delivery for the Dolnośląskie news bot."""
import html
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram_bot import send_to_telegram, telegram_html_anchor

log = logging.getLogger(__name__)
TZ = ZoneInfo("Europe/Warsaw")


def init_digest_db(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS digest_articles ("
        "id TEXT PRIMARY KEY, title TEXT NOT NULL, summary_en TEXT NOT NULL, "
        "url TEXT NOT NULL, source TEXT NOT NULL, article_date TEXT NOT NULL, "
        "sort_epoch INTEGER NOT NULL, queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "digested_at TIMESTAMP)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_digest_articles_pending ON digest_articles(digested_at, sort_epoch)")
    conn.commit()


def store_digest_article(conn, article, summary):
    sort_key = article["sort_key"]
    epoch = int(sort_key.timestamp()) if hasattr(sort_key, "timestamp") else int(datetime.now(TZ).timestamp())
    conn.execute(
        "INSERT OR IGNORE INTO digest_articles "
        "(id,title,summary_en,url,source,article_date,sort_epoch) VALUES (?,?,?,?,?,?,?)",
        (
            article["id"], article["title"], summary, article["link"],
            article.get("source", ""), article.get("date", ""), epoch,
        ),
    )
    conn.commit()


def _digest_hour_reached(hour: int) -> bool:
    return datetime.now(TZ).hour >= hour


def _already_sent_today(conn, today: str) -> bool:
    row = conn.execute("SELECT v FROM bot_kv WHERE k='daily_digest_date'").fetchone()
    return bool(row and row[0] == today)


def _set_sent_today(conn, today: str):
    conn.execute(
        "INSERT INTO bot_kv(k,v) VALUES('daily_digest_date',?) "
        "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
        (today,),
    )
    conn.commit()


def _pending(conn, max_scan=60):
    return conn.execute(
        "SELECT id,title,summary_en,url,source,article_date,sort_epoch "
        "FROM digest_articles WHERE digested_at IS NULL ORDER BY sort_epoch DESC LIMIT ?",
        (max_scan,),
    ).fetchall()


def _select_and_rank(client, rows, max_items):
    if not rows:
        return []
    lines = []
    for i, row in enumerate(rows, 1):
        _, title, summary, _, source, date, _ = row
        lines.append(f"{i}. TITLE: {title}\nSUMMARY: {summary}\nSOURCE: {source}\nDATE: {date}")
    prompt = (
        "You are selecting a concise daily local-news brief for a resident of Wroclaw, Poland. "
        "The goal is practical awareness: prioritize developments that can affect daily life, "
        "transport, infrastructure, public services, safety, local government, prices, weather, "
        "health, education, major regional developments, and important local events. "
        "Deprioritize celebrity, generic national politics, sports, trivial crime, advertising, "
        "and low-impact human-interest stories. Merge near-duplicates by selecting only the strongest item. "
        f"Select at most {max_items} items. Return ONLY a comma-separated list of the selected item numbers "
        "in importance order, with no other text.\n\n" + "\n\n".join(lines)
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=120,
            messages=[
                {"role": "system", "content": "You are a strict local-news editor."},
                {"role": "user", "content": prompt},
            ],
        )
        raw = (response.choices[0].message.content or "").strip()
        selected = []
        for token in raw.split(","):
            try:
                idx = int(token.strip()) - 1
            except ValueError:
                continue
            if 0 <= idx < len(rows) and idx not in selected:
                selected.append(idx)
            if len(selected) >= max_items:
                break
        return [rows[i] for i in selected]
    except Exception as exc:
        log.warning("Digest ranking failed: %s", exc)
        return rows[:max_items]


def _build_message(client, rows, max_items):
    selected = _select_and_rank(client, rows, max_items)
    if not selected:
        return None, []
    now = datetime.now(TZ)
    parts = [f"<b>Lower Silesia — Daily Brief | {now.strftime('%d %b %Y')}</b>"]
    parts.append("<i>What is worth knowing about the region today.</i>")
    for i, row in enumerate(selected, 1):
        _, title, summary, url, source, _, _ = row
        parts.append(
            f"\n<b>{i}. {html.escape(title, quote=False)}</b>\n"
            f"{html.escape(summary, quote=False)}\n"
            f"{telegram_html_anchor(url, source)}"
        )
    parts.append(f"\n<i>{len(selected)} stories</i>")
    return "\n".join(parts), selected


def maybe_send_daily_digest(conn, client, session, timeout, chat_id, dry_run, enabled, hour, max_items):
    if not enabled:
        return
    now = datetime.now(TZ)
    today = now.date().isoformat()
    if not _digest_hour_reached(hour) or _already_sent_today(conn, today):
        return
    rows = _pending(conn)
    if not rows:
        _set_sent_today(conn, today)
        log.info("Daily digest: no pending stories")
        return
    message, selected = _build_message(client, rows, max_items)
    if not message:
        return
    if dry_run:
        log.info("DRY_RUN daily digest: %s", message.replace("\n", " ")[:1000])
    else:
        send_to_telegram(session, message, chat_id=chat_id, timeout=timeout)

    # Every pending story belongs to this digest cycle. Only the selected stories
    # are shown, while the rest are intentionally discarded rather than carried
    # indefinitely into future digests.
    conn.execute(
        "UPDATE digest_articles SET digested_at=CURRENT_TIMESTAMP WHERE digested_at IS NULL"
    )
    _set_sent_today(conn, today)
    conn.commit()
    log.info("Daily digest sent: %d stories selected from %d pending", len(selected), len(rows))
