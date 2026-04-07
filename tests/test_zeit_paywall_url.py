"""Skip ZEIT print-issue and /2026 hub URLs without fetch or OpenAI."""

from unittest.mock import MagicMock

from config import (
    ZEIT_ARCHIVE_SKIP_URL,
    is_zeit_archive_skip_url,
    skip_admin_notify_for_article,
    zeit_archive_skip_reason,
)
from summarize import summarize_in_english


def test_zeit_print_issue_url_matches():
    url = "https://www.zeit.de/2026/15/klamotten-marketing-absurd-aldi-lidl-kfc-crocs"
    assert ZEIT_ARCHIVE_SKIP_URL.match(url)
    assert is_zeit_archive_skip_url(url)


def test_zeit_2026_hub_matches():
    assert is_zeit_archive_skip_url("https://www.zeit.de/2026")
    assert is_zeit_archive_skip_url("https://www.zeit.de/2026/")
    assert is_zeit_archive_skip_url("https://zeit.de/2026?x=1")


def test_zeit_skips_before_fetch_and_openai(monkeypatch):
    monkeypatch.setattr("summarize.fetch_article_body", lambda *_a, **_k: "")
    article = {
        "link": "https://www.zeit.de/2026/15/klamotten-marketing-absurd-aldi-lidl-kfc-crocs",
        "title": "Test",
        "summary": "Lead",
    }
    client = MagicMock()
    out, reason = summarize_in_english(client, MagicMock(), (1, 2), article)
    assert out is None
    assert reason == zeit_archive_skip_reason()
    assert reason.lower().startswith("rss teaser:")
    client.chat.completions.create.assert_not_called()


def test_zeit_news_url_not_matched():
    url = "https://www.zeit.de/news/2026-04/04/example-slug"
    assert ZEIT_ARCHIVE_SKIP_URL.match(url) is None
    assert is_zeit_archive_skip_url(url) is False


def test_zeit_skip_does_not_require_admin_dm():
    article = {"link": "https://www.zeit.de/2026/15/example", "title": "x"}
    assert skip_admin_notify_for_article(article, zeit_archive_skip_reason())


def test_m_zeit_subdomain_matches_archive_skip():
    assert is_zeit_archive_skip_url("https://m.zeit.de/2026/1/a")


def test_zeit_news_date_path_not_false_positive():
    """/news/2026-04/ is not the print volume path YEAR/ISSUE/."""
    url = "https://www.zeit.de/news/2026-04/05/warum-topjobs"
    assert is_zeit_archive_skip_url(url) is False
