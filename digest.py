"""Daily digest storage and delivery for the Dolnośląskie news bot."""
import html
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram_bot import send_to_telegram, telegram_html_anchor

log = logging.getLogger(__name__)
TZ = ZoneInfo("Europe/Warsaw")

# Telegram message limit is 4096 characters.
# Keep a safety margin for HTML entities / formatting.
TELEGRAM_SAFE_LIMIT = 3900


def init_digest_db(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS digest_articles ("
        "id TEXT PRIMARY KEY, title TEXT NOT NULL, summary_en TEXT NOT NULL, "
        "url TEXT NOT NULL, source TEXT NOT NULL, article_date TEXT NOT NULL, "
        "sort_epoch INTEGER NOT NULL, queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "digested_at TIMESTAMP)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_digest_articles_pending "
        "ON digest_articles(digested_at, sort_epoch)"
    )
    conn.commit()


def store_digest_article(conn, article, summary):
    sort_key = article["sort_key"]
    epoch = (
        int(sort_key.timestamp())
        if hasattr(sort_key, "timestamp")
        else int(datetime.now(TZ).timestamp())
    )
    conn.execute(
        "INSERT OR IGNORE INTO digest_articles "
        "(id,title,summary_en,url,source,article_date,sort_epoch) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            article["id"],
            article["title"],
            summary,
            article["link"],
            article.get("source", ""),
            article.get("date", ""),
            epoch,
        ),
    )
    conn.commit()


def _digest_hour_reached(hour: int) -> bool:
    return datetime.now(TZ).hour >= hour


def _already_sent_today(conn, today: str) -> bool:
    row = conn.execute(
        "SELECT v FROM bot_kv WHERE k='daily_digest_date'"
    ).fetchone()
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
        "FROM digest_articles "
        "WHERE digested_at IS NULL "
        "ORDER BY sort_epoch DESC LIMIT ?",
        (max_scan,),
    ).fetchall()


def _select_and_rank(client, rows, max_items):
    if not rows:
        return []

    lines = []
    for i, row in enumerate(rows, 1):
        _, title, summary, _, source, date, _ = row
        lines.append(
            f"{i}. TITLE: {title}\n"
            f"SUMMARY: {summary}\n"
            f"SOURCE: {source}\n"
            f"DATE: {date}"
        )

    prompt = (
        "You are selecting a concise daily local-news brief for a resident "
        "of Wroclaw, Poland. "
        "The goal is practical awareness: prioritize developments that can "
        "affect daily life, transport, infrastructure, public services, "
        "safety, local government, prices, weather, health, education, "
        "major regional developments, and important local events. "
        "Deprioritize celebrity, generic national politics, sports, "
        "trivial crime, advertising, and low-impact human-interest stories. "
        "Merge near-duplicates by selecting only the strongest item. "
        f"Select at most {max_items} items. "
        "Return ONLY a comma-separated list of the selected item numbers "
        "in importance order, with no other text.\n\n"
        + "\n\n".join(lines)
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=120,
            messages=[
                {
                    "role": "system",
                    "content": "You are a strict local-news editor.",
                },
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


def _build_message(rows, summaries=None):
    """Build one Telegram-safe HTML message.

    summaries optionally allows a caller to replace individual summaries
    without changing the database rows.
    """
    if not rows:
        return None

    now = datetime.now(TZ)

    parts = [
        f"<b>Lower Silesia — Daily Brief | {now.strftime('%d %b %Y')}</b>",
        "<i>What is worth knowing about the region today.</i>",
    ]

    for i, row in enumerate(rows, 1):
        _, title, summary, url, source, _, _ = row

        if summaries and i - 1 < len(summaries):
            summary = summaries[i - 1]

        parts.append(
            f"\n<b>{i}. {html.escape(title, quote=False)}</b>\n"
            f"{html.escape(summary, quote=False)}\n"
            f"{telegram_html_anchor(url, source)}"
        )

    parts.append(f"\n<i>{len(rows)} stories</i>")

    return "\n".join(parts)


def _fit_message(selected):
    """Fit the digest safely under Telegram's message-size limit.

    First remove the least-important selected stories.
    If a single story is still too long, shorten its summary.
    """
    if not selected:
        return None, []

    # First try the full selection.
    rows = list(selected)

    while rows:
        message = _build_message(rows)

        if message and len(message) <= TELEGRAM_SAFE_LIMIT:
            return message, rows

        # Remove the least important story first.
        if len(rows) > 1:
            rows.pop()
            continue

        # Only one story remains and it is still too long.
        row = rows[0]
        _, title, summary, url, source, _, _ = row

        # Preserve the title and source link; shorten only the summary.
        escaped_title = html.escape(title, quote=False)
        anchor = telegram_html_anchor(url, source)

        fixed = (
            f"<b>Lower Silesia — Daily Brief | "
            f"{datetime.now(TZ).strftime('%d %b %Y')}</b>\n"
            "<i>What is worth knowing about the region today.</i>\n\n"
            f"<b>1. {escaped_title}</b>\n"
        )

        suffix = f"\n{anchor}\n\n<i>1 story</i>"

        available = TELEGRAM_SAFE_LIMIT - len(fixed) - len(suffix)

        if available <= 50:
            shortened = "Summary unavailable."
        else:
            raw_summary = str(summary)
            shortened = raw_summary[: available - 3].rstrip() + "..."

        message = (
            fixed
            + html.escape(shortened, quote=False)
            + suffix
        )

        return message, rows

    return None, []


def maybe_send_daily_digest(
    conn,
    client,
    session,
    timeout,
    chat_id,
    dry_run,
    enabled,
    hour,
    max_items,
):
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

    selected = _select_and_rank(client, rows, max_items)

    if not selected:
        log.info("Daily digest: ranking returned no stories")
        return

    message, fitted_rows = _fit_message(selected)

    if not message:
        log.warning("Daily digest: could not build a Telegram-safe message")
        return

    log.info(
        "Daily digest prepared: selected=%d pending=%d chars=%d",
        len(fitted_rows),
        len(rows),
        len(message),
    )

    if dry_run:
        log.info(
            "DRY_RUN daily digest: %s",
            message.replace("\n", " ")[:1000],
        )
        return

    try:
        send_to_telegram(
            session,
            message,
            chat_id=chat_id,
            timeout=timeout,
        )
    except Exception:
        log.exception("Daily digest delivery failed")
        return

    # Only consume the pending stories after Telegram confirms delivery.
    #
    # Every pending story belongs to this digest cycle. The selected stories
    # are shown, while the remaining stories are intentionally discarded
    # rather than carried indefinitely into future digests.
    conn.execute(
        "UPDATE digest_articles "
        "SET digested_at=CURRENT_TIMESTAMP "
        "WHERE digested_at IS NULL"
    )

    _set_sent_today(conn, today)
    conn.commit()

    log.info(
        "Daily digest sent: selected=%d consumed=%d chars=%d",
        len(fitted_rows),
        len(rows),
        len(message),
    )
