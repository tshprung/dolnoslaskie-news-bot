"""Stage 2 retry ladder — OpenAI mocked."""

from unittest.mock import MagicMock

from summarize import summarize_in_hebrew


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content, finish_reason="stop"):
        self.message = _Msg(content)
        self.finish_reason = finish_reason


class _Resp:
    def __init__(self, content, finish_reason="stop"):
        self.choices = [_Choice(content, finish_reason)]


def _client_with_responses(*contents_and_reasons):
    seq = []
    for item in contents_and_reasons:
        if isinstance(item, tuple):
            seq.append(_Resp(item[0], item[1]))
        else:
            seq.append(_Resp(item))
    client = MagicMock()
    client.chat.completions.create.side_effect = seq
    return client


def test_insufficient_with_body_short_text(monkeypatch):
    monkeypatch.setattr(
        "summarize.fetch_article_body",
        lambda _session, _url, _to: "Kurz. " * 3,
    )
    article = {
        "link": "https://www.tagesschau.de/inland/test-1.html",
        "title": "Kurz",
        "summary": "",
    }
    client = _client_with_responses("GO", "INSUFFICIENT", "INSUFFICIENT")
    out, reason = summarize_in_hebrew(client, MagicMock(), (1, 2), article)
    assert out is None
    assert "paywall" in reason or "insufficient text" in reason


def test_insufficient_immediate_when_body_unreachable(monkeypatch):
    monkeypatch.setattr("summarize.fetch_article_body", lambda *_a, **_k: "")
    article = {
        "link": "https://www.zeit.de/test",
        "title": "Nur Titel",
        "summary": "Lead",
    }
    client = _client_with_responses("GO", "INSUFFICIENT")
    out, reason = summarize_in_hebrew(client, MagicMock(), (1, 2), article)
    assert out is None
    assert "no usable article text" in reason or "paywall" in reason


def test_stage2_latin_only_then_hebrew_retry(monkeypatch):
    body = "Umfrage: Mehrheit der Befragten in Berlin sieht die Reform skeptisch."
    monkeypatch.setattr("summarize.fetch_article_body", lambda *_a, **_k: body)
    article = {
        "link": "https://www.zeit.de/umfrage-test",
        "title": "Umfrage",
        "summary": "",
    }
    latin = "A survey found most respondents in Berlin were skeptical about the reform mentioned in the article."
    client = _client_with_responses("GO", latin)
    out, reason = summarize_in_hebrew(client, MagicMock(), (1, 2), article)
    assert reason is None
    assert out and ("survey" in out.lower() or "berlin" in out.lower())
    assert client.chat.completions.create.call_count == 2


def test_berlin_geo_mismatch(monkeypatch):
    body = (
        "Großbrand am Brandenburger Tor in Berlin; Feuerwehr im Einsatz. "
        * 10
    )
    monkeypatch.setattr("summarize.fetch_article_body", lambda *_a, **_k: body)
    article = {
        "link": "https://www.tagesschau.de/inland/berlin-1.html",
        "title": "Einsatz Berlin",
        "summary": "",
    }
    out_en = "A major fire near Brandenburger Tor in Berlin prompted a large firefighter response."
    client = _client_with_responses("GO", out_en)
    out, reason = summarize_in_hebrew(client, MagicMock(), (1, 2), article)
    assert out is not None
    assert reason is None
