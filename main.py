import html
import logging
import sqlite3
import time

from openai import OpenAI

from config import (
    ADMIN_TELEGRAM_ID,
    AGGREGATOR_URL_SKIP,
    DRY_RUN,
    DRY_RUN_MAX_POSTS,
    LISTICLE_TITLE_SKIP,
    SPORTS_KEYWORDS,
    TELEGRAM_LINK_PREVIEW_ENABLED,
    radio_wroc_ticker_skip_reason,
    should_skip_radio_wroc_ticker_title,
    should_skip_sponsored,
    should_skip_wroclaw_go_event_url,
    sponsored_skip_reason,
    skip_admin_notify_for_article,
    wroclaw_go_event_skip_reason,
)
from database import get_new_articles, init_db, record_seen_url
from dedup import deduplicate, is_english_near_duplicate, record_sent_en_snapshot, record_sent_snapshot
from http_util import make_http_session, request_timeout
from summarize import openai_client, summarize_in_english
from telegram_bot import notify_admin, send_to_telegram, telegram_html_anchor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)


def _mark_article_done(conn: sqlite3.Connection, article: dict) -> None:
    conn.execute("INSERT OR IGNORE INTO seen_articles (id) VALUES (?)", (article["id"],))
    record_seen_url(conn, article.get("url_norm", ""))
    conn.commit()


def main():
    conn = init_db()
    session = make_http_session()
    to = request_timeout()
    client: OpenAI = openai_client()

    if not ADMIN_TELEGRAM_ID:
        log.warning("ADMIN_TELEGRAM_ID is unset — failed articles will not DM you")

    new_articles = get_new_articles(conn, session=session, timeout=to)
    new_articles.sort(key=lambda a: a["sort_key"])
    new_articles = deduplicate(conn, new_articles)
    log.info(f"Found {len(new_articles)} new articles after deduplication")
    sent_count = 0

    for article in new_articles:
        try:
            if AGGREGATOR_URL_SKIP.search(article["link"]):
                log.info(f"Skipped (ticker/aggregator URL): {article['title'][:70]}")
                _mark_article_done(conn, article)
                continue
            if should_skip_wroclaw_go_event_url(article.get("link")):
                log.info(f"Skipped ({wroclaw_go_event_skip_reason()}): {article['title'][:70]}")
                _mark_article_done(conn, article)
                continue
            if LISTICLE_TITLE_SKIP.search(article["title"] or ""):
                log.info(f"Skipped (listicle/quiz keyword): {article['title'][:70]}")
                _mark_article_done(conn, article)
                continue
            if should_skip_radio_wroc_ticker_title(article.get("title")):
                log.info(f"Skipped ({radio_wroc_ticker_skip_reason()}): {article['title'][:70]}")
                _mark_article_done(conn, article)
                continue
            if SPORTS_KEYWORDS.search(article["title"]):
                log.info(f"Skipped (sports keyword): {article['title'][:70]}")
                _mark_article_done(conn, article)
                continue
            if should_skip_sponsored(article.get("title"), article.get("summary"), article.get("link")):
                log.info(f"Skipped ({sponsored_skip_reason()}): {article['title'][:70]}")
                _mark_article_done(conn, article)
                continue
            summary, skip_reason = summarize_in_english(client, session, to, article)
            if summary is None:
                if skip_reason:
                    log.info(f"Skipped ({skip_reason}): {article['title'][:70]}")
                    if not skip_admin_notify_for_article(article, skip_reason):
                        notify_admin(session, article, skip_reason, ADMIN_TELEGRAM_ID, to)
                else:
                    log.info(f"Skipped (classifier: SKIP): {article['title'][:70]}")
                _mark_article_done(conn, article)
                continue
            # Second-layer dedup: avoid posting near-identical English blurbs even if RSS metadata differs.
            dup_en, dup_detail = is_english_near_duplicate(conn, article["id"], summary, article["sort_key"])
            if dup_en:
                log.info("Skipped (%s): %s", dup_detail, article["title"][:70])
                _mark_article_done(conn, article)
                continue
            body = html.escape(summary, quote=False)
            footer_label = f"{article['source']} | {article['date']}"
            message = f"{body}\n\n{telegram_html_anchor(article['link'], footer_label)}"
            if TELEGRAM_LINK_PREVIEW_ENABLED:
                # Telegram generates the rich preview card (image) only for a raw URL,
                # not for HTML anchors. Put it on its own line like the screenshot.
                message = f"{message}\n{article['link']}"
            # Mark seen BEFORE sending so a crash after Telegram POST
            # doesn't cause reposts on the next cron run.
            _mark_article_done(conn, article)
            if DRY_RUN:
                log.info("DRY_RUN would send: %s", message.replace("\n", " ")[:240])
            else:
                send_to_telegram(session, message, timeout=to)
            record_sent_snapshot(conn, article)
            record_sent_en_snapshot(conn, article["id"], summary, article["sort_key"])
            conn.commit()
            log.info(f"Sent: {article['title'][:70]}")
            sent_count += 1
            if DRY_RUN and sent_count >= DRY_RUN_MAX_POSTS:
                log.info("DRY_RUN reached max posts (%s); stopping early", DRY_RUN_MAX_POSTS)
                break
            time.sleep(5)
        except Exception as e:
            log.exception("Error on article %s", article["id"])
            try:
                if not skip_admin_notify_for_article(article):
                    notify_admin(session, article, f"runtime error: {e}", ADMIN_TELEGRAM_ID, to)
            except Exception:
                pass

    conn.close()


if __name__ == "__main__":
    main()
