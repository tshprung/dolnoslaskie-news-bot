"""Daily digest storage and delivery for the Dolnośląskie news bot."""
import html
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram_bot import send_to_telegram, telegram_html_anchor

log = logging.getLogger(__name__)
TZ = ZoneInfo("Europe/Warsaw")

# Telegram message limit is 4096 characters.
# Keep a safety margin.
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


def _fallback_headline(title, summary):
    """Create a usable English fallback headline from the English summary.

    This is only used if the headline-generation JSON cannot be parsed.
    """
    text = " ".join(str(summary or "").split()).strip()

    if not text:
        return "Lower Silesia regional development"

    # Use the first sentence where possible.
    for separator in (". ", "! ", "? "):
        if separator in text:
            text = text.split(separator, 1)[0].strip()
            break

    if len(text) > 110:
        text = text[:107].rsplit(" ", 1)[0].rstrip() + "..."

    return text


def _select_and_rank(client, rows, max_items):
    if not rows:
        return [], {}

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
        "You are the editor of a concise daily local-news brief for a "
        "resident of Wroclaw, Poland.\n\n"
        "The goal is practical awareness of what is happening in "
        "Lower Silesia today. Prioritize developments that can affect "
        "daily life: transport, infrastructure, public services, safety, "
        "local government, prices, water, weather, health, education, "
        "major regional developments, and important local events.\n\n"
        "Deprioritize celebrity, generic national politics, sports, "
        "trivial crime, advertising, and low-impact human-interest stories.\n\n"
        "Merge near-duplicates by selecting only the strongest item.\n\n"
        f"Select at most {max_items} items in importance order.\n"
        "For every selected item, write a concise, factual English headline. "
        "Do not translate word-for-word if that produces unnatural English. "
        "The headline should describe the actual event and must not introduce "
        "facts that are not supported by the supplied title or summary.\n\n"
        "Return ONLY valid JSON in exactly this structure:\n"
        '{"items":[{"index":1,"headline":"English headline"},'
        '{"index":4,"headline":"English headline"}]}\n\n'
        "Do not include any explanation or additional keys.\n\n"
        + "\n\n".join(lines)
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=500,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a strict local-news editor. "
                        "Write natural, factual English headlines."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )

        raw = (response.choices[0].message.content or "").strip()
        data = json.loads(raw)

        items = data.get("items")
        if not isinstance(items, list):
            raise ValueError("Digest ranking response has no items list")

        selected = []
        headlines = {}

        for item in items:
            if not isinstance(item, dict):
                continue

            try:
                idx = int(item.get("index")) - 1
            except (TypeError, ValueError):
                continue

            if not (0 <= idx < len(rows)):
                continue

            if idx in [rows.index(r) for r in selected]:
                continue

            headline = str(item.get("headline") or "").strip()

            if not headline:
                continue

            selected.append(rows[idx])
            headlines[idx] = headline

            if len(selected) >= max_items:
                break

        if not selected:
            raise ValueError("Digest ranking returned no valid selections")

        # Make sure every selected item has a headline.
        for row in selected:
            idx = rows.index(row)
            if idx not in headlines:
                headlines[idx] = _fallback_headline(
                    row[1],
                    row[2],
                )

        return selected, headlines

    except Exception as exc:
        log.warning("Digest ranking failed: %s", exc)

        # Safe fallback: preserve the existing ranking behavior while
        # keeping the Telegram digest in English as much as possible.
        selected = rows[:max_items]
        headlines = {
            idx: _fallback_headline(row[1], row[2])
            for idx, row in enumerate(selected)
        }

        return selected, headlines


def _build_message(rows, headlines):
    if not rows:
        return None

    now = datetime.now(TZ)

    parts = [
        f"<b>Lower Silesia — Daily Brief | {now.strftime('%d %b %Y')}</b>",
        "<i>What is worth knowing about the region today.</i>",
    ]

    for i, row in enumerate(rows, 1):
        row_index = i - 1

        _, original_title, summary, url, source, _, _ = row

        headline = headlines.get(row_index)

        if not headline:
            headline = _fallback_headline(
                original_title,
                summary,
            )

        parts.append(
            f"\n<b>{i}. {html.escape(headline, quote=False)}</b>\n"
            f"{html.escape(summary, quote=False)}\n"
            f"{telegram_html_anchor(url, source)}"
        )

    parts.append(f"\n<i>{len(rows)} stories</i>")

    return "\n".join(parts)


def _fit_message(selected, headlines):
    """Fit the digest safely under Telegram's message-size limit.

    The least important selected stories are removed first.
    If a single story is still too long, only its summary is shortened.
    """
    if not selected:
        return None, [], {}

    rows = list(selected)
    current_headlines = dict(headlines)

    while rows:
        message = _build_message(rows, current_headlines)

        if message and len(message) <= TELEGRAM_SAFE_LIMIT:
            return message, rows, current_headlines

        if len(rows) > 1:
            removed = rows.pop()

            # Rebuild headline mapping after removing the last item.
            current_headlines = {
                i: current_headlines.get(i, "")
                for i in range(len(rows))
            }
            continue

        # One story remains and it is still too long.
        row = rows[0]
        _, original_title, summary, url, source, _, _ = row

        headline = current_headlines.get(
            0,
            _fallback_headline(original_title, summary),
        )

        header = (
            f"<b>Lower Silesia — Daily Brief | "
            f"{datetime.now(TZ).strftime('%d %b %Y')}</b>\n"
            "<i>What is worth knowing about the region today.</i>\n\n"
            f"<b>1. {html.escape(headline, quote=False)}</b>\n"
        )

        suffix = (
            f"\n{telegram_html_anchor(url, source)}"
            "\n\n<i>1 story</i>"
        )

        available = TELEGRAM_SAFE_LIMIT - len(header) - len(suffix)

        if available <= 50:
            shortened = "Summary unavailable."
        else:
            raw_summary = str(summary or "")
            shortened = (
                raw_summary[: max(1, available - 3)].rstrip()
                + "..."
            )

        message = (
            header
            + html.escape(shortened, quote=False)
            + suffix
        )

        return message, rows, {0: headline}

    return None, [], {}


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

    selected, headlines = _select_and_rank(
        client,
        rows,
        max_items,
    )

    if not selected:
        log.info("Daily digest: ranking returned no stories")
        return

    message, fitted_rows, fitted_headlines = _fit_message(
        selected,
        headlines,
    )

    if not message:
        log.warning(
            "Daily digest: could not build a Telegram-safe message"
        )
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

    # Only consume pending stories after Telegram confirms delivery.
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
