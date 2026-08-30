"""Daily digest storage and delivery for the Dolnośląskie news bot."""
import html
import json
import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram_bot import send_to_telegram, telegram_html_anchor

log = logging.getLogger(__name__)
TZ = ZoneInfo("Europe/Warsaw")

TELEGRAM_SAFE_LIMIT = 3900
MAX_HEADLINE_CHARS = 110
DIGEST_HISTORY_DAYS = 3
DIGEST_HISTORY_MAX_ROWS = 30


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
            article["id"], article["title"], summary, article["link"],
            article.get("source", ""), article.get("date", ""), epoch,
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
        "FROM digest_articles WHERE digested_at IS NULL "
        "ORDER BY sort_epoch DESC LIMIT ?",
        (max_scan,),
    ).fetchall()


def _recent_digest_history(conn, max_rows=DIGEST_HISTORY_MAX_ROWS):
    """Return recently consumed digest stories for cross-day duplicate avoidance."""
    return conn.execute(
        "SELECT id,title,summary_en,url,source,article_date,sort_epoch "
        "FROM digest_articles "
        "WHERE digested_at IS NOT NULL "
        "AND digested_at >= datetime('now', ?) "
        "ORDER BY digested_at DESC, sort_epoch DESC LIMIT ?",
        (f"-{DIGEST_HISTORY_DAYS} days", max_rows),
    ).fetchall()


def _fallback_headline(title, summary):
    """Create a usable English fallback headline from the English summary."""
    text = " ".join(str(summary or "").split()).strip()
    if not text:
        return "Lower Silesia regional development"

    for separator in (". ", "! ", "? "):
        if separator in text:
            text = text.split(separator, 1)[0].strip()
            break

    return _clean_headline(text)


def _clean_headline(headline):
    """Keep an LLM headline concise and never cut it mid-word."""
    text = " ".join(str(headline or "").split()).strip()
    if not text:
        return "Lower Silesia regional development"
    if len(text) <= MAX_HEADLINE_CHARS:
        return text

    shortened = text[: MAX_HEADLINE_CHARS - 3].rsplit(" ", 1)[0].rstrip()
    return (shortened or text[: MAX_HEADLINE_CHARS - 3]).rstrip(" .,:;-") + "..."


def _token_set(text):
    return {
        token for token in re.findall(r"[a-z0-9ąćęłńóśźż]{3,}", str(text).lower())
        if token not in {
            "the", "and", "for", "from", "with", "after", "before",
            "that", "this", "near", "under", "over", "into", "will",
            "wroclaw", "wrocław", "dolnoslaskie", "dolnośląskie",
        }
    }


def _near_duplicate(row_a, row_b):
    """Conservative deterministic duplicate check for selected stories."""
    title_a = row_a[1]
    title_b = row_b[1]
    if title_a.strip().lower() == title_b.strip().lower():
        return True

    a = _token_set(title_a)
    b = _token_set(title_b)
    if not a or not b:
        return False

    overlap = len(a & b) / min(len(a), len(b))
    jaccard = len(a & b) / len(a | b)
    return overlap >= 0.80 and jaccard >= 0.55


def _history_duplicate(row, history_row):
    """Use a stricter test when suppressing a story already covered on a prior day."""
    if row[3] and row[3] == history_row[3]:
        return True

    title_a = row[1].strip().lower()
    title_b = history_row[1].strip().lower()
    if title_a == title_b:
        return True

    a = _token_set(title_a)
    b = _token_set(title_b)
    if not a or not b:
        return False

    overlap = len(a & b) / min(len(a), len(b))
    jaccard = len(a & b) / len(a | b)
    return overlap >= 0.90 and jaccard >= 0.70


def _remove_recent_duplicates(rows, history):
    """Remove strong repeats of stories already covered in recent daily digests."""
    if not history:
        return rows

    result = []
    for row in rows:
        duplicate_of = None
        for previous in history:
            if _history_duplicate(row, previous):
                duplicate_of = previous
                break
        if duplicate_of is None:
            result.append(row)
        else:
            log.info(
                "Digest recent duplicate removed: %r ~= prior %r",
                row[1][:100], duplicate_of[1][:100],
            )
    return result


def _deduplicate_rows(rows):
    """Remove obvious duplicate events while preserving ranking order."""
    result = []
    for row in rows:
        duplicate_of = None
        for existing_row in result:
            if _near_duplicate(row, existing_row):
                duplicate_of = existing_row
                break
        if duplicate_of is None:
            result.append(row)
        else:
            log.info(
                "Digest duplicate removed: %r ~= %r",
                row[1][:100], duplicate_of[1][:100],
            )
    return result


def _select_rows(client, rows, max_items, history=None):
    """Ask the model which current rows to select, considering recent digest coverage."""
    if not rows:
        return []

    lines = []
    for i, row in enumerate(rows, 1):
        _, title, summary, _, source, date, _ = row
        lines.append(
            f"{i}. TITLE: {title}\nSUMMARY: {summary}\n"
            f"SOURCE: {source}\nDATE: {date}"
        )

    history_lines = []
    for i, row in enumerate(history or [], 1):
        _, title, _, _, source, date, _ = row
        history_lines.append(f"- {title} | {source} | {date}")
    history_block = "\n".join(history_lines) if history_lines else "(none)"

    prompt = (
        "You are the editor of a concise daily local-news brief for a resident "
        "of Wroclaw, Poland.\n\n"
        "Prioritize practical developments that can affect daily life: transport, "
        "infrastructure, public services, safety, local government, prices, water, "
        "weather, health, education, major regional developments, and important "
        "local events. Deprioritize celebrity, generic national politics, sports, "
        "trivial crime, advertising, and low-impact human-interest stories.\n\n"
        "Treat multiple articles about the same underlying event as ONE story. "
        "Never select two articles that report the same event. Choose the strongest "
        "or most informative version.\n\n"
        "The digest already covered the recent stories listed below. Do NOT select "
        "a current article merely because it is a new article about the same story. "
        "Select it only when there is a material new development that is useful to "
        "a resident (for example a decision, result, new restriction, reopening, "
        "new danger, deadline, or substantial change).\n\n"
        "RECENTLY COVERED STORIES:\n"
        f"{history_block}\n\n"
        f"Select at most {max_items} UNIQUE current events in importance order.\n"
        "Return ONLY valid JSON in exactly this structure:\n"
        '{"indices":[1,4,7]}\n\n'
        "The indices MUST refer to the numbered current articles above. Do not return headlines.\n\n"
        + "\n\n".join(lines)
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=150,
            messages=[
                {
                    "role": "system",
                    "content": "You are a strict local-news editor. Return only article indices.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        raw = (response.choices[0].message.content or "").strip()
        data = json.loads(raw)
        indices = data.get("indices")
        if not isinstance(indices, list):
            raise ValueError("Digest ranking response has no indices list")

        selected = []
        used = set()
        for value in indices:
            try:
                idx = int(value) - 1
            except (TypeError, ValueError):
                continue
            if not (0 <= idx < len(rows)) or idx in used:
                continue
            selected.append(rows[idx])
            used.add(idx)
            if len(selected) >= max_items:
                break

        if not selected:
            raise ValueError("Digest ranking returned no valid selections")

        return _deduplicate_rows(selected)

    except Exception as exc:
        log.warning("Digest ranking failed: %s", exc)
        return _deduplicate_rows(rows[:max_items])


def _generate_headline(client, row):
    """Generate a headline for exactly one row, eliminating cross-story pairing risk."""
    _, title, summary, _, _, _, _ = row
    prompt = (
        "Write one concise factual English headline for this ONE news story. "
        "The headline must describe only this story. Do not mention facts from any "
        "other story. Normally keep it under 90 characters. Do not add unsupported facts.\n\n"
        f"SOURCE TITLE: {title}\n"
        f"ENGLISH SUMMARY: {summary}\n\n"
        "Return ONLY the headline."
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=80,
            messages=[
                {
                    "role": "system",
                    "content": "You write concise factual English news headlines.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        headline = _clean_headline(response.choices[0].message.content or "")
        if headline and headline != "Lower Silesia regional development":
            return headline
    except Exception as exc:
        log.warning("Digest headline generation failed for %r: %s", title[:100], exc)

    return _fallback_headline(title, summary)


def _select_and_rank(client, rows, max_items, history=None):
    """Select stories first, then generate each headline from its own row."""
    selected_rows = _select_rows(client, rows, max_items, history=history)
    return [(row, _generate_headline(client, row)) for row in selected_rows]


def _build_message(pairs):
    if not pairs:
        return None

    now = datetime.now(TZ)
    parts = [
        f"<b>Lower Silesia — Daily Brief | {now.strftime('%d %b %Y')}</b>",
        "<i>What is worth knowing about the region today.</i>",
    ]

    for i, (row, headline) in enumerate(pairs, 1):
        _, _, summary, url, source, _, _ = row
        parts.append(
            f"\n<b>{i}. {html.escape(headline, quote=False)}</b>\n"
            f"{html.escape(summary, quote=False)}\n"
            f"{telegram_html_anchor(url, source)}"
        )

    parts.append(f"\n<i>{len(pairs)} stories</i>")
    return "\n".join(parts)


def _fit_message(selected_pairs):
    """Fit the digest safely under Telegram's message-size limit."""
    if not selected_pairs:
        return None, []

    pairs = list(selected_pairs)
    while pairs:
        message = _build_message(pairs)
        if message and len(message) <= TELEGRAM_SAFE_LIMIT:
            return message, pairs

        if len(pairs) > 1:
            pairs.pop()
            continue

        row, headline = pairs[0]
        _, _, summary, url, source, _, _ = row
        header = (
            f"<b>Lower Silesia — Daily Brief | {datetime.now(TZ).strftime('%d %b %Y')}</b>\n"
            "<i>What is worth knowing about the region today.</i>\n\n"
            f"<b>1. {html.escape(headline, quote=False)}</b>\n"
        )
        suffix = f"\n{telegram_html_anchor(url, source)}\n\n<i>1 story</i>"
        available = TELEGRAM_SAFE_LIMIT - len(header) - len(suffix)
        if available <= 50:
            shortened = "Summary unavailable."
        else:
            raw_summary = str(summary or "")
            shortened = raw_summary[: max(1, available - 3)].rstrip() + "..."

        message = header + html.escape(shortened, quote=False) + suffix
        return message, pairs

    return None, []


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

    history = _recent_digest_history(conn)
    rows = _remove_recent_duplicates(rows, history)
    if not rows:
        _set_sent_today(conn, today)
        log.info("Daily digest: all pending stories were already covered recently")
        return

    selected_pairs = _select_and_rank(client, rows, max_items, history=history)
    if not selected_pairs:
        log.info("Daily digest: ranking returned no stories")
        return

    message, fitted_pairs = _fit_message(selected_pairs)
    if not message:
        log.warning("Daily digest: could not build a Telegram-safe message")
        return

    log.info(
        "Daily digest prepared: selected=%d pending=%d history=%d chars=%d",
        len(fitted_pairs), len(rows), len(history), len(message),
    )

    if dry_run:
        log.info("DRY_RUN daily digest: %s", message.replace("\n", " ")[:1000])
        return

    try:
        send_to_telegram(session, message, chat_id=chat_id, timeout=timeout)
    except Exception:
        log.exception("Daily digest delivery failed")
        return

    conn.execute(
        "UPDATE digest_articles SET digested_at=CURRENT_TIMESTAMP WHERE digested_at IS NULL"
    )
    _set_sent_today(conn, today)
    conn.commit()

    log.info(
        "Daily digest sent: selected=%d consumed=%d chars=%d",
        len(fitted_pairs), len(rows), len(message),
    )
