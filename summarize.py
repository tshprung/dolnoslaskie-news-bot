"""OpenAI: classify + English summary for Dolnośląskie sources."""
import atexit
import html
import logging
import re
from urllib.parse import urlparse

from dataclasses import dataclass

import requests
from openai import OpenAI

from article_fetch import fetch_article_body
from config import (
    CLASSIFY_PROMPT,
    MAX_SUMMARY_WORDS,
    MAX_SUMMARY_WORDS_HARD,
    OPENAI_MAX_RETRIES,
    OPENAI_TIMEOUT_SEC,
    PAYWALLED_DOMAINS,
    STAGE2_INPUT_CHARS_DEFAULT,
    STAGE2_INPUT_CHARS_LONG_BODY,
    SYSTEM_PROMPT,
    discrimination_klagen_filler_skip_reason,
    fold_de,
    is_zeit_archive_skip_url,
    should_skip_discrimination_klagen_filler,
    should_skip_ultra_short_rss_item,
    ultra_short_rss_skip_reason,
    zeit_archive_skip_reason,
)

# Admin DM when Stage 2 cannot summarize (paywall/teaser/empty body).
_SKIPPED_PAYWALL_TEASER = (
    "insufficient text (paywall/teaser/login; not enough free content for summary)"
)
_SKIPPED_NO_BODY = "no usable article text (paywall, bot block, or empty fetch)"

log = logging.getLogger(__name__)

_SUMMARY_CAP = str(MAX_SUMMARY_WORDS)

@dataclass
class _RunTelemetry:
    classify_calls: int = 0
    stage2_calls: int = 0
    stage2_retries: int = 0
    body_fetched_chars: int = 0
    stage2_input_chars: int = 0


_TEL = _RunTelemetry()


@atexit.register
def _log_run_telemetry() -> None:
    if _TEL.classify_calls == 0 and _TEL.stage2_calls == 0:
        return
    avg_in = (_TEL.stage2_input_chars / _TEL.stage2_calls) if _TEL.stage2_calls else 0.0
    avg_body = (_TEL.body_fetched_chars / _TEL.classify_calls) if _TEL.classify_calls else 0.0
    log.info(
        "OpenAI telemetry: classify_calls=%d stage2_calls=%d stage2_retries=%d avg_stage2_input_chars=%.0f avg_body_chars=%.0f",
        _TEL.classify_calls,
        _TEL.stage2_calls,
        _TEL.stage2_retries,
        avg_in,
        avg_body,
    )

_SANITIZE_EN_LINE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


def _sanitize_english_summary_line(result: str) -> str:
    """Decode HTML entities; strip control chars; keep punctuation and diacritics."""
    return _SANITIZE_EN_LINE.sub("", html.unescape(result)).strip()


_POLISH_PROSE_MARKERS = re.compile(
    r"(?is)"
    r"\b("
    r"b[eę]dzie|bedzie|"
    r"gdzie|"
    r"om[oó]wi|omowi|"
    r"kwesti[eę]|kwestie|"
    r"zwierz[aą]t|zwierzat|"
    r"miast(?:ach|a|em|ami)?|"
    r"radny|radna|"
    r"go[sś]ciem|gosciem|"
    r"naj[sś]wie|najswie|"
    r"wiadomo[sś]ci|wiadomosci"
    r")\b"
)


def _looks_like_polish_prose(s: str) -> bool:
    """
    Heuristic: catch cases where Stage 2 ignores the English-only instruction.
    Tuned to avoid false positives on English that only contains Polish placenames.
    """
    t = (s or "").strip()
    if not t:
        return False
    if _POLISH_PROSE_MARKERS.search(t):
        return True
    # Strong signal: multiple Polish-specific letters outside all-caps tokens (often names).
    diac = set(re.findall(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]", t))
    if len(diac) >= 3:
        return True
    return False


def _rewrite_summary_to_english(client: OpenAI, polish_line: str) -> str:
    """One-shot repair when Stage 2 returns Polish prose."""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=220,
        messages=[
            {
                "role": "system",
                "content": (
                    "You rewrite Polish news blurbs into clear factual English for Telegram. "
                    "Output ONLY 1-2 sentences. "
                    "Keep Polish placenames in Latin as in the source (Wrocław, Dolnośląskie). "
                    "Do not prefix with labels. Do not output SKIP/INSUFFICIENT."
                ),
            },
            {
                "role": "user",
                "content": f"Polish blurb:\n{polish_line.strip()}\n\nRewrite in English:",
            },
        ],
    )
    return (response.choices[0].message.content or "").strip()


_LEADING_LABEL_PATTERNS = (
    r"^english\s*:\s*",
    r"^english\s*-\s*",
    r"^summary\s*:\s*",
    r"^summary\s*-\s*",
    # Echo of old prompt line "English (≤50 words)".
    r"^english\s*\([^)]*words?\s*\)\s*:?\s*",
)

_STAGE2_ANTI_ECHO = (
    "Your last reply was only a format or word-count label, not a news summary. "
    "Reply with ONLY 1-2 factual English sentences about the article, "
    "or exactly SKIP/INSUFFICIENT per your rules. "
    "Do not output 'English (…)', word counts, or meta labels."
)


def strip_leading_summary_labels(text: str) -> str:
    """Remove model echoes like 'English:' / 'Summary:' before the real summary."""
    s = text.strip()
    for _ in range(4):
        prev = s
        for pat in _LEADING_LABEL_PATTERNS:
            s = re.sub(pat, "", s, count=1, flags=re.IGNORECASE).lstrip()
        if s == prev:
            break
    s = re.sub(
        r"(?is)^english\s*\([^)]{0,80}?words?\s*\)\s*(\n\s*)+",
        "",
        s,
        count=1,
    )
    return s.lstrip()


def _is_meta_wordcount_echo(s: str) -> bool:
    """True when the model replied with only a word-count / format stub (no real summary)."""
    t = (s or "").strip()
    if not t or len(t) > 120:
        return False
    if re.match(
        r"(?is)^english\s*[\(\[][≤=<\d\s.\u2264]{0,24}words?\s*[\)\]]\s*$",
        t,
    ):
        return True
    if re.match(
        r"(?is)^english\s*[-–—]\s*\d+\s*sentences?.{0,60}words?\s*$",
        t,
    ):
        return True
    return False


_DE_DOMESTIC_NOT_ISRAEL = re.compile(
    r"(?is)"
    r"(?:"
    r"\bdeutschland\b|\bbundesrepublik\b|\bbrd\b|\bbundesland\w*|\bbundes\w*regierung\b|"
    r"\bbundestag\b|\bbundesrat\b|\blandtag\b|"
    r"\bberlin\b|\bm(u|ü)nchen\b|\bhamburg\b|\bk(ö|o)ln\b|\bfrankfurt\b|\bstuttgart\b|"
    r"\bd(u|ü)sseldorf\b|\bleipzig\b|\bdresden\b|\bhannover\b|\bbremen\b|\bn(u|ü)rnberg\b|"
    r"sachsen-anhalt|sachsenanhalt|niedersachsen|schleswig-holstein|mecklenburg|brandenburg|"
    r"baden-w(u|ü)rttemberg|\bbayern\b|\bhessen\b|\bsaarland\b|"
    r"nrw|nordrhein|rheinland|westfalen|th(u|ü)ringen|\bsachsen\b|"
    r"klinikum|krankenhaus|krankenhauser|landkreis|stadtkreis"
    r")",
)


def _source_suggests_germany_domestic_not_israel(german_blob: str) -> bool:
    """Legacy helper; kept for compatibility with copied tests/config."""
    f = fold_de(german_blob[:8000])
    if not _DE_DOMESTIC_NOT_ISRAEL.search(f):
        return False
    if re.search(r"israel|tel\s*aviv|jerusalem|jerosolym|haifa", f):
        return False
    return True


def _mentions_major_israeli_city(text: str) -> bool:
    return bool(re.search(r"(?is)\btel\s*[-]?\s*aviv\b|\bjerusalem\b", text))


def classify(client: OpenAI, text: str):
    _TEL.classify_calls += 1
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=5,
        messages=[
            {"role": "system", "content": CLASSIFY_PROMPT},
            {"role": "user", "content": f"Article: {text[:500]}"},
        ],
    )
    result = response.choices[0].message.content.strip().upper()
    if result.startswith("SKIP"):
        return "SKIP"
    return "GO"


def _rss_excerpt_substantial(article: dict) -> bool:
    summary = (article.get("summary") or "").strip()
    title = (article.get("title") or "").strip()
    if len(summary) >= 200:
        return True
    if len(title) + len(summary) >= 300:
        return True
    return len(summary) >= 120 and len(title) + len(summary) >= 220


def summarize_in_english(
    client: OpenAI,
    session: requests.Session,
    http_timeout: tuple,
    article: dict,
):
    rss_text = article["title"]
    if article["summary"]:
        rss_text += ". " + article["summary"]

    if should_skip_ultra_short_rss_item(article.get("title"), article.get("summary")):
        return None, ultra_short_rss_skip_reason()

    domain = urlparse(article["link"]).netloc.lstrip("www.")
    if domain in PAYWALLED_DOMAINS:
        return None, f"paywalled domain ({domain})"
    if is_zeit_archive_skip_url(article.get("link")):
        return None, zeit_archive_skip_reason()
    body, fetch_err = fetch_article_body(session, article["link"], http_timeout)
    if body:
        _TEL.body_fetched_chars += len(body)
    fetch_blocked_reason = fetch_err
    if should_skip_discrimination_klagen_filler(
        article.get("title"),
        article.get("summary"),
        article.get("link"),
        fetched_body=body,
    ):
        return None, discrimination_klagen_filler_skip_reason()
    text = (article["title"] + ". " + body) if body else rss_text
    body_available = (
        bool(body and body.strip())
        or _rss_excerpt_substantial(article)
        or len(rss_text.strip()) >= 280
    )
    if fetch_blocked_reason and not body_available:
        # If we were blocked (403/WAF/etc) AND the RSS excerpt is too thin to summarize,
        # keep the explicit reason so main.py can DM the admin.
        return None, fetch_blocked_reason

    decision = classify(client, text)
    if decision == "SKIP":
        return None, None

    stage2_limit = int(STAGE2_INPUT_CHARS_DEFAULT)
    if not _rss_excerpt_substantial(article) and len(body or "") >= 4500:
        stage2_limit = int(STAGE2_INPUT_CHARS_LONG_BODY)

    def call_stage2(user_blob: str):
        _TEL.stage2_calls += 1
        _TEL.stage2_input_chars += len(user_blob)
        return client.chat.completions.create(
            model="gpt-4o",
            max_tokens=400,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_blob},
            ],
        )

    insufficient_retry_note = (
        "Use any concrete facts given. Short pieces OK: TV/radio = guests, shows, times; "
        "interviews and wires = who + what they said or decided. "
        "INSUFFICIENT only if the body adds almost nothing beyond the headline "
        "(no names, agencies, dates, numbers, decisions)."
    )
    strong_insuf_note = (
        "The body is long with reporting: names, titles, quotes, attribution. "
        "Examples: Bundestag, Bundesregierung, EU diplomacy, Länder — summarize who said/did what. "
        "Reply INSUFFICIENT only when there are no extractable facts beyond the headline."
    )
    short_retry_note = f"Output a real English sentence (not empty); max {_SUMMARY_CAP} words."

    result = ""
    insuf_hint_tier = 0
    pending_anti_echo = False
    for attempt in range(3):
        if attempt >= 1:
            _TEL.stage2_retries += 1
        user_blob = f"Article: {text[:stage2_limit]}"
        if insuf_hint_tier == 1:
            user_blob = f"{user_blob}\n\n{insufficient_retry_note}"
        elif insuf_hint_tier == 2:
            user_blob = f"{user_blob}\n\n{strong_insuf_note}"
        elif attempt >= 1 and len(result) > 0 and len(result) < 15:
            user_blob = f"{user_blob}\n\n{short_retry_note}"
        if pending_anti_echo:
            user_blob = f"{user_blob}\n\n{_STAGE2_ANTI_ECHO}"
            pending_anti_echo = False

        response = call_stage2(user_blob)
        finish = response.choices[0].finish_reason
        if finish == "content_filter":
            return None, "blocked by content policy (content_filter)"
        if finish == "length":
            return None, "response truncated"
        result = (response.choices[0].message.content or "").strip()

        if result.upper().startswith("SKIP"):
            return None, None

        if _is_meta_wordcount_echo(result):
            log.warning("Stage 2 returned word-count label echo (attempt %s)", attempt + 1)
            if attempt >= 2:
                return None, "model returned prompt label instead of summary"
            pending_anti_echo = True
            continue

        is_insuf = result.upper().startswith("INSUF")
        if is_insuf:
            if not body_available:
                return None, _SKIPPED_NO_BODY
            if insuf_hint_tier == 0:
                insuf_hint_tier = 1
                log.info("Stage 2 INSUFFICIENT — retry with hint (schedule/thin body)")
                continue
            if insuf_hint_tier == 1 and len(text) >= 1200:
                insuf_hint_tier = 2
                log.info("Stage 2 INSUFFICIENT — retry with long-body hint")
                continue
            return None, _SKIPPED_PAYWALL_TEASER

        if len(result) >= 15:
            break
        log.warning(f"Stage 2 response too short (attempt {attempt + 1}): '{result}'")
        if attempt >= 2:
            return None, "response too short after retry"

    if result.upper().startswith("INSUF"):
        if not body_available:
            return None, _SKIPPED_NO_BODY
        return None, _SKIPPED_PAYWALL_TEASER
    if len(result) < 15:
        return None, "response too short after retry"

    result = strip_leading_summary_labels(result)

    result = _sanitize_english_summary_line(result)
    if not result:
        return None, "sanitization left empty result"

    if _looks_like_polish_prose(result):
        log.warning("Stage 2 returned Polish prose — running English rewrite pass")
        try:
            fixed = _rewrite_summary_to_english(client, result)
        except Exception as e:
            return None, f"model returned Polish summary; rewrite failed ({e})"
        fixed = strip_leading_summary_labels(fixed)
        fixed = _sanitize_english_summary_line(fixed)
        if not fixed:
            return None, "model returned Polish summary; rewrite produced empty text"
        if fixed.upper().startswith("SKIP") or fixed.upper().startswith("INSUF"):
            return None, "model returned Polish summary; rewrite returned control token"
        if _looks_like_polish_prose(fixed):
            return None, "model returned Polish summary; rewrite still not English"
        result = fixed

    word_count = len(result.split())
    if word_count > MAX_SUMMARY_WORDS_HARD:
        return None, f"summary too long ({word_count} words, max {MAX_SUMMARY_WORDS})"

    return result, None


def openai_client() -> OpenAI:
    return OpenAI(timeout=OPENAI_TIMEOUT_SEC, max_retries=OPENAI_MAX_RETRIES)
