import argparse
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
    routine_football_event_skip_reason,
    should_skip_routine_football_event,
    should_skip_radio_wroc_ticker_title,
    should_skip_sponsored,
    should_skip_wroclaw_go_event_url,
    sponsored_skip_reason,
    skip_admin_notify_for_article,
    wroclaw_go_event_skip_reason,
    hala_staroci_event_skip_reason,
    should_skip_hala_staroci_event,
)
from database import get_new_articles, init_db, record_seen_url
from digest import init_digest_db, maybe_send_daily_digest, store_digest_article
from http_util import make_http_session, request_timeout
from summarize import openai_client, summarize_in_english
from telegram_bot import notify_admin
from retry_queue import clear_retry, record_retry, retryable_summary_failure

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _mark_article_done(conn: sqlite3.Connection, article: dict) -> None:
    conn.execute("INSERT OR IGNORE INTO seen_articles (id) VALUES (?)", (article["id"],))
    record_seen_url(conn, article.get("url_norm", ""))
    clear_retry(conn, article.get("url_norm", ""))
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


def _deliver_digest(conn, client, session, timeout):
    enabled, hour, max_items = _digest_config()
    maybe_send_daily_digest(
        conn, client, session, timeout, CHANNEL_ID, DRY_RUN, enabled, hour, max_items,
    )


def main(mode="all"):
    conn = init_db()
    init_digest_db(conn)
    session = make_http_session()
    to = request_timeout()
    client: OpenAI = openai_client()

    if mode == "digest":
        try:
            _deliver_digest(conn, client, session, to)
        finally:
            conn.close()
        return

    if not ADMIN_TELEGRAM_ID:
        log.warning("ADMIN_TELEGRAM_ID is unset — failed articles will not DM you")

    new_articles = get_new_articles(conn, session=session, timeout=to)
    # Exact IDs/URLs are filtered during collection. Keep related reports so the
    # daily editor can choose the latest outcome rather than lose useful updates.
    new_articles.sort(key=lambda a: a["sort_key"], reverse=True)
    log.info("Found %s new articles for editorial review", len(new_articles))
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
            if should_skip_hala_staroci_event(article.get("link")):
                log.info("Skipped (%s): %s", hala_staroci_event_skip_reason(), article["title"][:70])
                _mark_article_done(conn, article)
                continue
            if should_skip_routine_football_event(article.get("title"), article.get("link")):
                log.info("Skipped (%s): %s", routine_football_event_skip_reason(), article["title"][:70])
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
                if retryable_summary_failure(skip_reason):
                    record_retry(conn, article["url_norm"], skip_reason)
                    continue
                if skip_reason:
                    log.info("Skipped (%s): %s", skip_reason, article["title"][:70])
                    if not skip_admin_notify_for_article(article, skip_reason):
                        notify_admin(session, article, skip_reason, ADMIN_TELEGRAM_ID, to)
                else:
                    log.info("Skipped (classifier: SKIP): %s", article["title"][:70])
                _mark_article_done(conn, article)
                continue

            store_digest_article(conn, article, summary)
            _mark_article_done(conn, article)
            conn.commit()
            log.info("Queued for daily digest: %s", article["title"][:70])
            queued_count += 1

            if DRY_RUN and queued_count >= DRY_RUN_MAX_POSTS:
                log.info("DRY_RUN reached max posts (%s); stopping early", DRY_RUN_MAX_POSTS)
                break
            time.sleep(1)
        except Exception as e:
            log.exception("Error on article %s", article["id"])
            record_retry(conn, article["url_norm"], f"runtime error: {type(e).__name__}")
            try:
                if not skip_admin_notify_for_article(article):
                    notify_admin(session, article, f"runtime error: {e}", ADMIN_TELEGRAM_ID, to)
            except Exception:
                pass

    try:
        if mode == "all":
            _deliver_digest(conn, client, session, to)
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("all", "collect", "digest"), default="all")
    main(parser.parse_args().mode)

