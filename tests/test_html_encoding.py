"""Regression: UTF-8 HTML without charset must not decode as Latin-1."""
import requests

from article_fetch import _html_text
from summarize import _sanitize_english_summary_line


def test_html_text_prefers_utf8_when_requests_default_is_latin1():
    raw = "<p>München — Straßenbahn</p>".encode("utf-8")
    r = requests.Response()
    r.status_code = 200
    r._content = raw
    r.headers = {"Content-Type": "text/html"}
    r.encoding = "iso-8859-1"
    text = _html_text(r)
    assert "München" in text
    assert "Straßenbahn" in text


def test_html_numeric_entities_not_turned_into_spurious_34():
    """&#34; must not become \"34;\" after stripping & and # from the summary line."""
    s = 'Wrocław council says &#34;more safety&#34; next week.'
    out = _sanitize_english_summary_line(s)
    assert "34;" not in out
    assert "council" in out.lower()
