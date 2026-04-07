"""Low-salience tabloid discrimination-lawsuit filler — skip before Hebrew."""

from unittest.mock import MagicMock

from config import (
    discrimination_klagen_filler_skip_reason,
    should_skip_discrimination_klagen_filler,
    skip_admin_notify_for_reason,
)
from summarize import summarize_in_hebrew


def test_bild_slug_diskriminierungs_klagen_miese_geschaeft():
    url = (
        "https://www.bild.de/news/inland/"
        "machen-wir-tausend-das-miese-geschaeft-mit-den-diskriminierungs-klagen-69c12fb3dc49aa83e414ca5c"
    )
    assert should_skip_discrimination_klagen_filler("BILD - Home", "", url)
    assert skip_admin_notify_for_reason(discrimination_klagen_filler_skip_reason())


def test_summarize_short_circuits_on_slug_without_openai(monkeypatch):
    monkeypatch.setattr("summarize.fetch_article_body", lambda *_a, **_k: "")
    article = {
        "link": (
            "https://www.bild.de/news/inland/"
            "machen-wir-tausend-das-miese-geschaeft-mit-den-diskriminierungs-klagen-x"
        ),
        "title": "BILD - Home",
        "summary": "",
    }
    client = MagicMock()
    out, reason = summarize_in_hebrew(client, MagicMock(), (1, 2), article)
    assert out is None
    assert reason == discrimination_klagen_filler_skip_reason()
    client.chat.completions.create.assert_not_called()


def test_major_verdict_not_skipped_without_tabloid_signals():
    assert not should_skip_discrimination_klagen_filler(
        "Siemens unterliegt vor Arbeitsgericht",
        "Diskriminierung: Schmerzensgeld in Millionenhöhe",
        "https://www.faz.net/aktuell/wirtschaft/siemens-arbeitsgericht-diskriminierung.html",
        fetched_body=(
            "Das Arbeitsgericht München sprach der Klägerin recht. "
            "Der Konzern kündigte Berufung an."
        ),
    )
