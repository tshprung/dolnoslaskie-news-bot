"""Stage 2 retry ladder — OpenAI mocked."""

from unittest.mock import MagicMock

from summarize import summarize_in_english


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
        lambda _session, _url, _to: ("Kurz. " * 3, None),
    )
    article = {
        "link": "https://www.tagesschau.de/inland/test-1.html",
        "title": "Kurz",
        "summary": "",
    }
    client = _client_with_responses("GO", "INSUFFICIENT", "INSUFFICIENT")
    out, reason = summarize_in_english(client, MagicMock(), (1, 2), article)
    assert out is None
    assert "paywall" in reason or "insufficient text" in reason


def test_insufficient_immediate_when_body_unreachable(monkeypatch):
    monkeypatch.setattr("summarize.fetch_article_body", lambda *_a, **_k: ("", None))
    article = {
        "link": "https://www.zeit.de/test",
        "title": "Nur Titel",
        "summary": "Lead",
    }
    client = _client_with_responses("GO", "INSUFFICIENT")
    out, reason = summarize_in_english(client, MagicMock(), (1, 2), article)
    assert out is None
    assert "no usable article text" in reason or "paywall" in reason


def test_fetch_blocked_403_still_summarizes_when_rss_excerpt_substantial(monkeypatch):
    monkeypatch.setattr(
        "summarize.fetch_article_body",
        lambda *_a, **_k: ("", "fetch blocked (403 Forbidden): https://example.com/x"),
    )
    article = {
        "link": "https://example.com/x",
        "title": "Wrocław: Police appeal for witnesses after MPK incident",
        "summary": (
            "Police are looking for a young man after an assault on a ticket inspector at Gajowicka tram stop in Wrocław. "
            "Witnesses are asked to contact police and provide any recordings from the area. "
            "The incident happened after a group refused to show documents and one suspect fled, knocking the inspector to the ground."
        ),
    }
    client = _client_with_responses("GO", "Police are seeking witnesses after an assault on an MPK ticket inspector at a Wrocław tram stop.")
    out, reason = summarize_in_english(client, MagicMock(), (1, 2), article)
    assert reason is None
    assert out is not None and "police" in out.lower()


def test_stage2_latin_only_then_english_ok(monkeypatch):
    body = "Umfrage: Mehrheit der Befragten in Berlin sieht die Reform skeptisch."
    monkeypatch.setattr("summarize.fetch_article_body", lambda *_a, **_k: (body, None))
    article = {
        "link": "https://www.zeit.de/umfrage-test",
        "title": "Umfrage",
        "summary": "",
    }
    latin = "A survey found most respondents in Berlin were skeptical about the reform mentioned in the article."
    client = _client_with_responses("GO", latin)
    out, reason = summarize_in_english(client, MagicMock(), (1, 2), article)
    assert reason is None
    assert out and ("survey" in out.lower() or "berlin" in out.lower())
    assert client.chat.completions.create.call_count == 2


def test_stage2_wordcount_label_echo_retries(monkeypatch):
    body = (
        "Wrocław police announced temporary traffic changes on Legnicka Street during sewer repairs."
    )
    monkeypatch.setattr("summarize.fetch_article_body", lambda *_a, **_k: (body, None))
    article = {
        "link": "https://www.example.com/wro-traffic",
        "title": "Legnicka",
        "summary": "",
    }
    client = _client_with_responses(
        "GO",
        "English (≤50 words)",
        "Police outlined temporary traffic changes on Legnicka Street in Wrocław during repairs.",
    )
    out, reason = summarize_in_english(client, MagicMock(), (1, 2), article)
    assert reason is None
    assert out and ("wrocław" in out.lower() or "legnicka" in out.lower())
    assert client.chat.completions.create.call_count == 3


def test_stage2_polish_output_triggers_english_rewrite(monkeypatch):
    body = (
        "Radny Robert Maślak, specjalista od ochrony przyrody, będzie gościem Radia Wrocław, "
        "gdzie omówi kwestie dzikich zwierząt w miastach."
    )
    monkeypatch.setattr("summarize.fetch_article_body", lambda *_a, **_k: (body, None))
    article = {
        "link": "https://www.radiowroclaw.pl/articles/view/159826",
        "title": "Gość Radia Wrocław",
        "summary": "",
    }
    pl = (
        "Radny Robert Maślak, specjalista od ochrony przyrody, będzie gościem Radia Wrocław, "
        "gdzie omówi kwestie dzikich zwierząt w miastach."
    )
    en = (
        "Wrocław councillor and nature-protection specialist Robert Maślak will be a guest on Radio Wrocław "
        "to discuss wild animals in cities."
    )
    client = _client_with_responses("GO", pl, en)
    out, reason = summarize_in_english(client, MagicMock(), (1, 2), article)
    assert reason is None
    assert out and "radio" in out.lower()
    assert client.chat.completions.create.call_count == 3


def test_berlin_geo_mismatch(monkeypatch):
    body = (
        "Großbrand am Brandenburger Tor in Berlin; Feuerwehr im Einsatz. "
        * 10
    )
    monkeypatch.setattr("summarize.fetch_article_body", lambda *_a, **_k: (body, None))
    article = {
        "link": "https://www.tagesschau.de/inland/berlin-1.html",
        "title": "Einsatz Berlin",
        "summary": "",
    }
    out_en = "A major fire near Brandenburger Tor in Berlin prompted a large firefighter response."
    client = _client_with_responses("GO", out_en)
    out, reason = summarize_in_english(client, MagicMock(), (1, 2), article)
    assert out is not None
    assert reason is None
