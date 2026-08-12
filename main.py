import logging
import os
import sqlite3
import time

from openai import OpenAI

from config import (
    ADMIN_TELEGRAM_ID,
    AGGREGATOR_URL_SKIP,
    CHANNEL_ID,
    DRY_RUN,
    DRY_RUN_MAX_POSTS,
    LISTICLE_TITLE_SKIP,
    SPORTS_KEYWORDS,
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
from digest import init_digest_db, maybe_send_daily_digest, store_digest_article
from http_util import make_http_session, request_timeout
from summarize import openai_client, summarize_in_english
from telegram_bot import notify_admin

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _mark_article_done(conn: sqlite3.Connection, article: dict) -> None:
    conn.execute("INSERT OR IGNORE INTO seen_articles (id) VALUES (?)", (article["id"],))
    record_seen_url(conn, article.get("url_norm", ""))
    conn.commit()


def _digest_config():
    enabled = os.environ.get("NEWS_DIGEST_ENABLED", "1").strip() == "1"
    try:
        hour = int(os.environ.get("NEWS_DIGEST_HOUR", "19"))
    except ValueError:
        hour = 19
    try:
        max_items = max(1, min(15, int(os.environ.get("NEWS_DIGEST_MAX_ITEMS", "10"))))
    except ValueError:
        max_items = 10
    return enabled, max(0, min(23, hour)), max_items


def main():
    conn = init_db()
    init_digest_db(conn)
    session = make_http_session()
    to = request_timeout()
    client: OpenAI = openai_client()

    if not ADMIN_TELEGRAM_ID:
        log.warning("ADMIN_TELEGRAM_ID is unset — failed articles will not DM you")

    new_articles = get_new_articles(conn, session=session, timeout=to)
    new_articles.sort(key=lambda a: a["sort_key"])
    new_articles = deduplicate(conn, new_articles)
    log.info("Found %s new articles after deduplication", len(new_articles))
    queued_count = 0

    for article in new_articles:
        try:
            if AGGREGATOR_URL_SKIP.search(article["link"]):
                log.info("Skipped (ticker/aggregator URL): %s", article["title"][:70])
                _mark_article_done(conn, article)
                continue
            if should_skip_wroclaw_go_event_url(article.get("link")):
                log.info("Skipped (%s): %s", wroclaw_go_event_skip_reason(), article["title"][:70])
                _mark_article_done(conn, article)
                continue
            if LISTICLE_TITLE_SKIP.search(article["title"] or ""):
                log.info("Skipped (listicle/quiz keyword): %s", article["title"][:70])
                _mark_article_done(conn, article)
                continue
            if should_skip_radio_wroc_ticker_title(article.get("title")):
                log.info("Skipped (%s): %s", radio_wroc_ticker_skip_reason(), article["title"][:70])
                _mark_article_done(conn, article)
                continue
            if SPORTS_KEYWORDS.search(article["title"]):
                log.info("Skipped (sports keyword): %s", article["title"][:70])
                _mark_article_done(conn, article)
                continue
            if should_skip_sponsored(article.get("title"), article.get("summary"), article.get("link")):
                log.info("Skipped (%s): %s", sponsored_skip_reason(), article["title"][:70])
                _mark_article_done(conn, article)
                continue

            summary, skip_reason = summarize_in_english(client, session, to, article)
            if summary is None:
                if skip_reason:
                    log.info("Skipped (%s): %s", skip_reason, article["title"][:70])
                    if not skip_admin_notify_for_article(article, skip_reason):
                        notify_admin(session, article, skip_reason, ADMIN_TELEGRAM_ID, to)
                else:
                    log.info("Skipped (classifier: SKIP): %s", article["title"][:70])
                _mark_article_done(conn, article)
                continue

            dup_en, dup_detail = is_english_near_duplicate(conn, article["id"], summary, article["sort_key"])
            if dup_en:
                log.info("Skipped (%s): %s", dup_detail, article["title"][:70])
                _mark_article_done(conn, article)
                continue

            store_digest_article(conn, article, summary)
            _mark_article_done(conn, article)
            record_sent_snapshot(conn, article)
            record_sent_en_snapshot(conn, article["id"], summary, article["sort_key"])
            conn.commit()
            log.info("Queued for daily digest: %s", article["title"][:70])
            queued_count += 1

            if DRY_RUN and queued_count >= DRY_RUN_MAX_POSTS:
                log.info("DRY_RUN reached max posts (%s); stopping early", DRY_RUN_MAX_POSTS)
                break
            time.sleep(1)
        except Exception as e:
            log.exception("Error on article %s", article["id"])
            try:
                if not skip_admin_notify_for_article(article):
                    notify_admin(session, article, f"runtime error: {e}", ADMIN_TELEGRAM_ID, to)
            except Exception:
                pass

    digest_enabled, digest_hour, digest_max_items = _digest_config()
    try:
        maybe_send_daily_digest(
            conn, client, session, to, CHANNEL_ID,
            DRY_RUN, digest_enabled, digest_hour, digest_max_items,
        )
    except Exception:
        log.exception("Daily digest delivery failed")

    conn.close()


if __name__ == "__main__":
    main()
