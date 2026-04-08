"""Static config, env, prompts (no I/O)."""
import os
import re
import unicodedata
from pathlib import Path

FEEDS = [
    # Wrocław official portal (local and reliable; tested)
    "https://www.wroclaw.pl/dla-mieszkanca/rss",
    "https://www.wroclaw.pl/komunikacja/rss",
    "https://www.wroclaw.pl/urzad/rss",
    "https://www.wroclaw.pl/przedsiebiorczy-wroclaw/rss",
    "https://www.wroclaw.pl/zielony-wroclaw/rss",
    "https://www.wroclaw.pl/akademicki-wroclaw/rss",
    "https://www.wroclaw.pl/rozmawia/rss",
    "https://www.wroclaw.pl/kultura/rss",
    "https://www.wroclaw.pl/ua/rss",
    # Not added: wroclaw.pl/sport/rss — channel scope skips sports (wasted fetch/classify).
    # Regional news outlets (RSS confirmed)
    # Nasze Miasto Wrocław (section feed; root /rss/ hits Cloudflare for bots)
    "https://wroclaw.naszemiasto.pl/rss/artykuly/1212.xml",
    "https://www.radiowroclaw.pl/articles/rss",
    "https://tuwroclaw.com/rss",
    # Gazeta Wrocławska (RSS exists; pre-skip obvious listicles to reduce cost)
    "https://gazetawroclawska.pl/rss",
    # Lower Silesia (Dolnośląskie) regional admin/government beat
    "https://portalsamorzadowy.pl/rss/dolnoslaskie.xml",
]

# Non-RSS sources (hourly scrape of listing pages).
SCRAPE_SOURCES = [
    {
        "key": "24wroclaw",
        "list_url": "https://24wroclaw.pl/wiadomosci/",
    },
    {
        "key": "echo24",
        "list_url": "https://echo24.tv/",
    },
]
# Gate scraping so RSS can run more often without extra traffic.
SCRAPE_SOURCES_MIN_INTERVAL_SEC = int(os.environ.get("SCRAPE_SOURCES_MIN_INTERVAL_SEC", "3600"))
# Per-run cap: avoid bursts if a layout change yields junk links.
SCRAPE_SOURCES_MAX_NEW_URLS = int(os.environ.get("SCRAPE_SOURCES_MAX_NEW_URLS", "25"))
SCRAPE_SOURCES_JITTER_MIN_SEC = float(os.environ.get("SCRAPE_SOURCES_JITTER_MIN_SEC", "1"))
SCRAPE_SOURCES_JITTER_MAX_SEC = float(os.environ.get("SCRAPE_SOURCES_JITTER_MAX_SEC", "3"))

# Cheap pre-skip for low-signal listicles/quizzes that would otherwise waste OpenAI calls.
# Keep this conservative; the classifier will handle borderline cases.
LISTICLE_TITLE_SKIP = re.compile(
    r"(?is)\b("
    r"quiz|horoskop|imieniu|"
    r"tak\s+wygl[aą]d(?:a|aj[aą])|tak\s+teraz\s+wygl[aą]d(?:a|aj[aą])|"
    r"sp[oó]jrz|zobacz|"
    r"najmniejsz|najpi[eę]kniejsz|"
    r"gotowe\s+pomys[lł]y|[zż]yczenia"
    r")\b"
)

# Radio Wrocław RSS emits a rolling "latest news" hub row, not one story (thin / mixed headlines).
RADIO_WROC_TICKER_TITLE_SKIP = re.compile(
    r"(?is)aktualno[sś]ci\s+radia\s+wroc[lł]aw",
)


def should_skip_radio_wroc_ticker_title(title: str | None) -> bool:
    if not title or not isinstance(title, str):
        return False
    return bool(RADIO_WROC_TICKER_TITLE_SKIP.search(title.strip()))


def radio_wroc_ticker_skip_reason() -> str:
    return "rss teaser: Radio Wrocław aktualności ticker (hub, not one article)"

# Guard against stale RSS items resurfacing.
# We only ingest items from the last 24 hours.
MAX_ARTICLE_AGE_HOURS = 24

DEDUP_WINDOW_HOURS = 8
DEDUP_JACCARD_MIN = 0.20
DEDUP_DICE_MIN = 0.45
DEDUP_DICE_RELAXED = 0.38
DEDUP_STRONG_INTERSECTION = 6
DEDUP_JACCARD_RELAXED = 0.15
DEDUP_OVERLAP_MIN = 0.34
DEDUP_OVERLAP_MIN_TOKENS = 4
DEDUP_OVERLAP_SET_MIN = 5
DEDUP_OVERLAP_LOOSE = 0.30
DEDUP_CONTENT_SUMMARY_CHARS = 4000

_DEDUP_SHORT_TOKENS_OK = frozenset(
    {
        "ue",
        "usa",
        "uk",
        "pl",
        "cbśp",
        "nfz",
        "pks",
        "pksy",
        "pko",
        "pkw",
        "pis",
        "po",
        "psl",
        "lewica",
        "kghm",
        "mpk",
        "pesa",
        "kw",
        "wrocław",
        "wroclaw",
    }
)

_TOPIC_DEDUP_TAGS = frozenset()
TOPIC_DEDUP_MIN_LEXICAL = 2
TOPIC_DEDUP_MIN_LEXICAL_WEATHER = 1

# RSS items that point at multi-story tickers — summaries mix beats (bad for channel).
AGGREGATOR_URL_SKIP = re.compile(
    r"zdfheute\.de/.+schlagzeilen-\d+\.html(?:$|[?#])",
    re.IGNORECASE,
)

# DIE ZEIT: print issues /year/issue/… (usually ZEIT+) and year hub zeit.de/2026 (Jahrgang index).
# Must not match /news/2026-04/… (date slug is not the print volume path).
ZEIT_ARCHIVE_SKIP_URL = re.compile(
    r"^https?://(?:[a-z0-9-]+\.)?zeit\.de/(?:\d{4}/\d{1,2}/|2026(?:/|$|\?))",
    re.IGNORECASE,
)


def is_zeit_archive_skip_url(url: str | None) -> bool:
    if not url or not isinstance(url, str):
        return False
    u = url.strip()
    if u.startswith("//"):
        u = "https:" + u
    elif not re.match(r"^https?://", u, re.I) and re.match(
        r"(?:[a-z0-9-]+\.)?zeit\.de/", u, re.I
    ):
        u = "https://" + u
    return bool(ZEIT_ARCHIVE_SKIP_URL.match(u))


def zeit_archive_skip_reason() -> str:
    return "rss teaser: ZEIT print issue or zeit.de/2026/… hub (skip)"


def discrimination_klagen_filler_skip_reason() -> str:
    return "rss teaser: tabloid discrimination-lawsuit single case (no national beat)"


def should_skip_discrimination_klagen_filler(
    title: str | None,
    summary: str | None,
    link: str | None,
    fetched_body: str | None = None,
) -> bool:
    """
    Skip low-salience tabloid pieces: one anonymous / initials plaintiff, labor court,
    discrimination damages, judge doubts „business model“ — not law reform or major scandal.
    """
    blob = f"{title or ''}\n{summary or ''}\n{link or ''}"
    if fetched_body:
        blob += "\n__body__\n" + fetched_body.strip()[:12000]
    if not blob.strip():
        return False
    f = fold_de(blob)
    link_l = (link or "").lower()

    # BILD-style URL slug often encodes the angle before body fetch.
    if re.search(r"diskriminierungs", link_l) and re.search(
        r"miese|tausend|klagen|klager|abzoc|geschaft|gewinn", link_l
    ):
        return True

    if not re.search(
        r"diskriminier|arbeitsgericht|arbeit\s*gericht|schmerzensgeld|verklag|klage\b",
        f,
    ):
        return False

    if re.search(
        r"miese\s+geschaft|geschaftsmodell|rechtsgeschaft|abzocke|"
        r"tausend[\s-]*euro|machen[\s-]*wir[\s-]*tausend|"
        r"zweifel\w*.{0,90}(motiv|vorgehen|ernst|rechthab)|"
        r"richter.{0,130}zweifel|"
        r"gewinn\w*.{0,50}(klage|motiv|absicht)|"
        r"prozessbetrug|rechtem\w*geschaft",
        f,
    ):
        return True

    return False


def fold_pl(token: str) -> str:
    """Lowercase Polish-ish fold: strip accents/diacritics (ł→l)."""
    s = unicodedata.normalize("NFC", token)
    s = s.replace("ł", "l").replace("Ł", "l")
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower()

# Backwards-compatible aliases (some copied helpers/tests may still call these).
fold_de = fold_pl
fold_pt = fold_pl

POLISH_STOPWORDS = frozenset(
    fold_pl(w)
    for w in """
    i oraz albo lub lecz jednak ale
    nie tak tez też już jeszcze bardzo bardziej mniej
    w we na do od z ze za dla przez bez po pod nad między miedzy
    że ze który ktory która ktora które ktore którymi ktorymi
    to ten ta te tego tej tych tym tymi
    jest są sa były byly był byl będzie bedzie byłyśmy bylismy
    o u a
    się sie
    dziś dzisiaj jutro wczoraj teraz
    www http https com pl
    """.split()
)

SPORTS_KEYWORDS = re.compile(
    r"\b(sport|piłka|pilka|nożna|nozna|ekstraklasa|liga\s+mistrzów|liga\s+europy|"
    r"mecz|gole?|trener|kibic|fc\s+[\w.-]+|"
    r"siatkówka|siatkowka|koszykówka|koszykowka|żużel|zuzel|boks|tenis|"
    r"f1|formuła\s*1|formula\s*1|olimpiad|wimbledon|nba|nfl|nhl|golf|rugby)\b",
    re.IGNORECASE,
)

SPONSORED_SKIP_RE = re.compile(
    r"(?is)(materiał\s+sponsorowany|material\s+sponsorowany|reklama|advertorial|\bpartner\b)"
)


def should_skip_sponsored(title: str | None, summary: str | None, link: str | None) -> bool:
    blob = f"{title or ''}\n{summary or ''}\n{link or ''}".strip()
    if not blob:
        return False
    return bool(SPONSORED_SKIP_RE.search(blob))


def sponsored_skip_reason() -> str:
    return "rss teaser: sponsored/advertorial content"

_HARD_NEWS_SIGNALS = re.compile(
    r"(?is)"
    r"(?:"
    r"\b\d{2,}\b|"
    r"festnahme|verhaft|angeklagt|prozess|urteil|gericht|"
    r"tote|verletzte|"
    r"bundestag|bundesregierung|ministerium|"
    r"anschlag|explosion|brand|"
    r"streik|"
    r"\beu\b|nato|"
    r")"
)


def should_skip_ultra_short_rss_item(title: str | None, summary: str | None) -> bool:
    t = (title or "").strip()
    s = (summary or "").strip()
    combined_len = len(t) + len(s)
    if combined_len >= 160:
        return False
    if len(s) >= 120:
        return False
    if _HARD_NEWS_SIGNALS.search(f"{t}\n{s}"):
        return False
    return combined_len >= 60


def ultra_short_rss_skip_reason() -> str:
    return "rss teaser: too short to summarize (skip to save tokens)"

PAYWALLED_DOMAINS = frozenset()  # add domains if fetch keeps hitting hard paywalls

MAX_SUMMARY_WORDS = 50
MAX_SUMMARY_WORDS_HARD = 60

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHANNEL_ID = os.environ["TELEGRAM_CHANNEL_ID"]
ADMIN_TELEGRAM_ID = os.environ.get("ADMIN_TELEGRAM_ID")
DB_PATH = Path(os.environ.get("DB_PATH", "/opt/dolnoslaskie_news/seen.db"))
DISPLAY_TZ = "Europe/Warsaw"

DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"
DRY_RUN_MAX_POSTS = int(os.environ.get("DRY_RUN_MAX_POSTS", "5"))

# Telegram: show link preview card (image) like in screenshot.
TELEGRAM_LINK_PREVIEW_ENABLED = os.environ.get("TELEGRAM_LINK_PREVIEW_ENABLED", "1") == "1"

WEEKLY_ANNOUNCE_ENABLED = os.environ.get("WEEKLY_ANNOUNCE_ENABLED", "1") == "1"
WEEKLY_ANNOUNCE_TZ = os.environ.get("WEEKLY_ANNOUNCE_TZ", "Europe/Warsaw")
WEEKLY_ANNOUNCE_WEEKDAY = int(os.environ.get("WEEKLY_ANNOUNCE_WEEKDAY", "6"))
WEEKLY_ANNOUNCE_HOUR = int(os.environ.get("WEEKLY_ANNOUNCE_HOUR", "18"))
WEEKLY_ANNOUNCE_SUPPORT_EMAIL = os.environ.get(
    "WEEKLY_ANNOUNCE_SUPPORT_EMAIL", "tshprung@gmail.com"
)
WEEKLY_ANNOUNCE_KOFI_URL = os.environ.get(
    "WEEKLY_ANNOUNCE_KOFI_URL", "https://ko-fi.com/talshprung"
)

_SUMMARY_CAP = str(MAX_SUMMARY_WORDS)
SYSTEM_PROMPT = (
    "English Telegram blurbs from Polish local/regional media (Dolnośląskie). Readers: **English speakers living in Poland** who want "
    "useful local news from **Wrocław and the Dolnośląskie voivodeship**.\n"
    "**Channel scope — Dolnośląskie only:** Cover items that clearly happen in, affect, or are governed by "
    "**Dolnośląskie** (including **Wrocław**, Legnica, Wałbrzych, Jelenia Góra, Lubin, Głogów, Świdnica, etc.). "
    "Poland-wide politics is **GO** only if it has a clear and specific Dolnośląskie/Wrocław angle.\n"
    "GEO: keep **place names in the original Polish Latin spelling** (Wrocław, Dolnośląskie, Wałbrzych). "
    "Never invent locations.\n\n"
    "Reply with exactly **one** line and **no** preamble.\n"
    "**Either** the token SKIP or INSUFFICIENT with the short reason (as below), "
    f"**or** only the factual English summary: **1–2 sentences, at most {_SUMMARY_CAP} words total**.\n"
    "Never reply with a meta line about format (do **not** output word-count parentheses, "
    "and do **not** write lines like 'English (≤N words)' or 'English - 1-2 sentences').\n\n"
    "SKIP - sports.\n"
    "SKIP - outside Dolnośląskie: stories that are clearly about another region/country with no direct Dolnośląskie/Wrocław tie.\n"
    "SKIP - service/lifestyle and low-signal noise: shopping/coupons/listicles, horoscopes/quizzes, travel/restaurant 'what to do', "
    "celebrity/showbiz, and micro-local updates like minor traffic closures or small incidents without broader public impact.\n"
    "SKIP - weather micro-updates: keep only major warnings/extremes or rate-limited forecast beats.\n"
    "SKIP - markets daily churn (crypto/stock up-down today) unless there is a concrete enforcement/regulatory decision, major platform outage, "
    "or clear local impact.\n"
    "INSUFFICIENT - only when the body truly adds almost nothing beyond the title: "
    "no names, no agencies, no dates or numbers, no attributed claims, no decision in one clause.\n\n"
    "If the Polish text names people, agencies, dates, figures, decisions, or quotes — summarize in English; "
    "not INSUFFICIENT.\n\n"
    "When you summarize, write **only** the summary—never prefix with English:, Summary:, or similar labels. "
    "Use Latin script. Keep **every Polish placename in Latin as in the source** (Wrocław, Dolnośląskie). "
    "Paraphrase, no quotes. Use clear, standard English.\n\n"
    "Do not translate the administrative term **województwo**; keep it in Latin as **województwo**.\n\n"
    "International/EU: **GO** only when the article explicitly connects it to Dolnośląskie/Wrocław (local officials, local impact). "
    "If it's a generic foreign story with no local tie—SKIP.\n\n"
    "Nested time / old quotes in a current story: When the Polish text ties today's news to words spoken or roles held "
    "in an earlier year, the English must make the chain explicit: "
    "who is speaking now; if only the outlet recalls past context, say so; "
    "and separately who originally said it, with year and role **then**."
)

CLASSIFY_PROMPT = (
    "**Dolnośląskie (Wrocław + Lower Silesia) — local channel.**\n"
    "**GO** if the excerpt clearly concerns **Dolnośląskie / Wrocław** (events in-region, local institutions, services, transport, safety, courts, economy).\n"
    "**SKIP** if: sports; or the story **lacks a direct Dolnośląskie/Wrocław tie** (another region/country only).\n"
    "**SKIP** also for: celebrity/showbiz, lifestyle/service listicles (shopping/coupons/tips), horoscopes/quizzes, "
    "micro-local traffic/minor incidents without wider impact, and routine markets churn with no concrete decision.\n"
    "One word: SKIP or GO."
)

# Admin Telegram: skip noisy expected skips (same idea as Polish channel).
SKIP_NOTIFY_EXEMPT_PREFIXES = ("rss teaser:",)

def skip_admin_notify_for_reason(reason: str | None) -> bool:
    if not reason:
        return False
    r = reason.lower()
    return any(r.startswith(p) for p in SKIP_NOTIFY_EXEMPT_PREFIXES)


def skip_admin_notify_for_article(article: dict | None, reason: str | None = None) -> bool:
    if skip_admin_notify_for_reason(reason):
        return True
    return bool(is_zeit_archive_skip_url((article or {}).get("link")))


REQUEST_CONNECT_TIMEOUT = 5
REQUEST_READ_TIMEOUT = 20
HTTP_RETRY_TOTAL = 3
HTTP_RETRY_BACKOFF = 0.5
HTTP_STATUS_FORCELIST = (502, 503, 504)

OPENAI_TIMEOUT_SEC = 90.0
OPENAI_MAX_RETRIES = 2
