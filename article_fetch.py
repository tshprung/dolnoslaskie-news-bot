"""Fetch full article HTML and extract plain text."""
import json
import logging
import re
from urllib.parse import urljoin, urlparse

import requests

log = logging.getLogger(__name__)

_BAD_DEFAULT_ENCODINGS = frozenset({"iso-8859-1", "windows-1252"})

_MAX_BODY_CHARS = 8000


def _trim_boilerplate(text: str) -> str:
    if not text:
        return ""
    lines = [ln.strip() for ln in text.splitlines()]
    cleaned: list[str] = []
    for ln in lines:
        if len(ln) < 14:
            continue
        low = ln.lower()
        if any(
            k in low
            for k in (
                "cookies",
                "datenschutz",
                "impressum",
                "agb",
                "anmelden",
                "registrieren",
                "abonnement",
                "abo",
                "jetzt testen",
                "mehr zum thema",
                "lesen sie auch",
                "hier weiterlesen",
                "teilen",
                "newsletter",
            )
        ):
            continue
        cleaned.append(ln)
    out = "\n".join(cleaned).strip()
    if len(out) > _MAX_BODY_CHARS:
        out = out[:_MAX_BODY_CHARS].rsplit("\n", 1)[0].strip() or out[:_MAX_BODY_CHARS].strip()
    return out


def _html_text(response: requests.Response) -> str:
    """Decode HTML with a plausible charset (avoids mojibake when charset is wrong)."""
    raw = response.content
    enc = (response.encoding or "").lower()
    if enc and enc not in _BAD_DEFAULT_ENCODINGS:
        try:
            return raw.decode(response.encoding)
        except (UnicodeDecodeError, LookupError, TypeError):
            pass
    apparent = getattr(response, "apparent_encoding", None) or "utf-8"
    for candidate in (apparent, "utf-8", "cp1252"):
        try:
            return raw.decode(candidate)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _article_body_from_jsonld(page_html: str) -> str:
    for m in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page_html,
        re.DOTALL | re.IGNORECASE,
    ):
        raw = m.group(1).strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            candidates = data.get("@graph", [data])
        elif isinstance(data, list):
            candidates = data
        else:
            continue
        for item in candidates:
            if not isinstance(item, dict):
                continue
            t = item.get("@type")
            if isinstance(t, list):
                types = t
            elif isinstance(t, str):
                types = [t]
            else:
                types = []
            if not any(x in ("NewsArticle", "Article") for x in types):
                continue
            body = item.get("articleBody")
            if isinstance(body, str) and len(body.strip()) > 150:
                return body.strip()
    return ""


def _article_body_from_dom(stripped_html: str) -> str:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return ""

    def cleanup_root(r):
        for sel in (
            "ad-default",
            "aside",
            ".ods-m-bullet-list",
            ".ods-o-authorship-bottom",
            ".ods-c-share-buttons-wrapper",
            ".ods-m-socials-stream",
            ".ods-m-tts-player",
            ".ods-o-authorship-top",
            ".ods-c-actionbar",
            ".ods-c-modal-premium",
            ".ods-o-onetchat-widget-chat",
        ):
            for tag in r.select(sel):
                tag.decompose()

    soup = BeautifulSoup(stripped_html, "html.parser")
    for jid in ("pianoOffer", "pianoInfo"):
        for tag in soup.find_all(id=jid):
            tag.decompose()

    root = soup.select_one("[class*='ods-article-body']")
    if root is None:
        root = soup.find("article")
    if root is None:
        return ""
    scope = root

    cleanup_root(scope)
    block = scope.get_text(separator="\n", strip=True)
    lines = [ln for ln in (x.strip() for x in block.splitlines()) if len(ln) > 12]
    primary = "\n".join(lines)

    paragraph_chunks = []
    for p in scope.find_all("p"):
        if p.find_parent("aside"):
            continue
        chunk = p.get_text(separator=" ", strip=True)
        if len(chunk) >= 20:
            paragraph_chunks.append(chunk)
    paragraph_body = "\n".join(paragraph_chunks)

    body_chunks = []
    for div in scope.select("div.ods-a-body-text"):
        chunk = div.get_text(separator=" ", strip=True)
        if len(chunk) > 25:
            body_chunks.append(chunk)
    fallback = "\n".join(body_chunks)

    best = primary
    if len(fallback) > len(best):
        best = fallback
    _para_substantial = len(paragraph_body) >= max(
        200, int(0.38 * max(len(primary), 1))
    )
    if len(paragraph_body) >= 180:
        if len(paragraph_body) > len(best):
            best = paragraph_body
        elif (
            best is primary
            and len(primary) > len(paragraph_body) + 80
            and _para_substantial
        ):
            best = paragraph_body
    return best


def _article_body_from_dom_wroclaw(stripped_html: str) -> str:
    """
    wroclaw.pl pages often have the meaningful content under <main>, while <article>
    can be short or dominated by "follow us / Google News" boilerplate.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return ""

    soup = BeautifulSoup(stripped_html, "html.parser")
    main = soup.find("main")
    if main is None:
        return ""

    for tag in main.select("header, nav, footer, aside, form"):
        tag.decompose()

    text = main.get_text(separator="\n", strip=True)
    lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 20]
    out = "\n".join(lines).strip()
    return out


def fetch_article_body(
    session: requests.Session, url: str, timeout: tuple
) -> tuple[str, str | None]:
    paywall_signals = [
        "zaloguj się",
        "registrieren",
        "anmelden",
        "abonnement",
        "paywall",
        "nutzerkonto",
        "bitte melden sie sich an",
        "abopflichtiger",
        "abopflichtig",
        "z+ (abopflichtiger",
        # Portuguese
        "assinar",
        "assinatura",
        "subscrição",
        "subscricao",
        "iniciar sessão",
        "iniciar sessao",
        "entrar",
        "registar",
        "registre-se",
        "conteúdo exclusivo",
        "conteudo exclusivo",
    ]
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
        }
        resp = session.get(url, timeout=timeout, headers=headers)
        resp.raise_for_status()
        page_html = _html_text(resp)

        text = _article_body_from_jsonld(page_html)
        if len(text) >= 200:
            if any(s in text.lower() for s in paywall_signals) and len(text) < 500:
                log.warning(f"Paywall detected at {url}, ignoring fetched content")
                return ""
            text = _trim_boilerplate(text)
            log.info(f"Fetched {len(text)} chars (JSON-LD) from {url}")
            return text, None

        stripped = re.sub(
            r"<script\b[^>]*>.*?</script>", " ", page_html, flags=re.DOTALL | re.IGNORECASE
        )
        stripped = re.sub(
            r"<style\b[^>]*>.*?</style>", " ", stripped, flags=re.DOTALL | re.IGNORECASE
        )

        text = ""
        if "wroclaw.pl/" in url:
            text = _article_body_from_dom_wroclaw(stripped)
        if len(text) < 250:
            text = _article_body_from_dom(stripped)
        if len(text) >= 250:
            if any(s in text.lower() for s in paywall_signals) and len(text) < 500:
                log.warning(f"Paywall detected at {url}, ignoring fetched content")
                return "", "insufficient text (paywall/teaser/login; not enough free content for summary)"
            text = _trim_boilerplate(text.strip())
            log.info(f"Fetched {len(text)} chars (DOM) from {url}")
            return text, None

        def extract_paragraphs(source):
            paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", source, re.DOTALL)
            return " ".join(
                re.sub(r"<[^>]+>", "", p).strip() for p in paragraphs if len(p) > 40
            )

        article_match = re.search(r"<article[^>]*>(.*?)</article>", stripped, re.DOTALL)
        if not article_match:
            article_match = re.search(
                r'<section[^>]*class="[^"]*\bart_content\b[^"]*"[^>]*>(.*?)</section>',
                stripped,
                re.DOTALL | re.IGNORECASE,
            )
        text = ""
        if article_match:
            text = extract_paragraphs(article_match.group(1)).strip()
        if len(text) < 300:
            text = extract_paragraphs(stripped).strip()
        if any(s in text.lower() for s in paywall_signals) and len(text) < 500:
            log.warning(f"Paywall detected at {url}, ignoring fetched content")
            return "", "insufficient text (paywall/teaser/login; not enough free content for summary)"
        text = _trim_boilerplate(text.strip())
        log.info(f"Fetched {len(text)} chars from {url}")
        return text, None
    except requests.HTTPError as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status == 403:
            return "", f"fetch blocked (403 Forbidden): {url}"
        return "", f"fetch failed (HTTP {status}): {url}"
    except Exception as e:
        log.warning(f"Could not fetch article body from {url}: {e}")
        return "", f"fetch failed: {url}"


def _norm_host(host: str) -> str:
    h = (host or "").strip().lower()
    if h.startswith("www."):
        h = h[4:]
    return h


def _registrable_domain(host: str) -> str:
    """
    Best-effort "registrable" domain without extra deps.
    For most PL outlets this is good enough (e.g. wiadomosci.wp.pl -> wp.pl).
    """
    h = _norm_host(host)
    parts = [p for p in h.split(".") if p]
    if len(parts) < 2:
        return h
    return ".".join(parts[-2:])


def extract_article_image_url(page_html: str, page_url: str, strict: bool = True) -> str | None:
    """
    Extract a plausible hero image URL from HTML metadata (no network):
    - Open Graph: <meta property="og:image" ...>
    - Twitter:   <meta name="twitter:image" ...>
    - JSON-LD:   "image": "..." / ["..."] / [{"url":"..."}]

    Safety filters:
    - https only, reject data URIs
    - strict host mode: same host as article URL
    - non-strict: same registrable domain (best-effort)
    - reject obvious logo/icon/sprite assets
    """
    html = page_html or ""
    base = (page_url or "").strip()
    if not base:
        return None

    base_host = _norm_host(urlparse(base).netloc)
    if not base_host:
        return None

    def norm_and_filter(raw_url: str | None) -> str | None:
        u = (raw_url or "").strip()
        if not u:
            return None
        if u.startswith("//"):
            u = "https:" + u
        u = urljoin(base, u)
        p = urlparse(u)
        if p.scheme.lower() != "https":
            return None
        if not p.netloc:
            return None

        host = _norm_host(p.netloc)
        if strict:
            if host != base_host:
                return None
        else:
            if _registrable_domain(host) != _registrable_domain(base_host):
                return None

        path_l = (p.path or "").lower()
        if any(k in path_l for k in ("logo", "favicon", "sprite", "icon", "blank")):
            return None
        if re.search(r"(?i)\b(logo|favicon|sprite|icon)\b", u):
            return None

        # Basic extension sanity: allow common image extensions, but also allow
        # extensionless CDN URLs (some outlets do this). If it looks like a script/css, reject.
        if re.search(r"(?i)\.(svg|css|js)(?:$|[?#])", u):
            return None
        return u

    def meta_content(pattern: str) -> str | None:
        m = re.search(pattern, html, flags=re.IGNORECASE)
        if not m:
            return None
        return m.group(1).strip()

    # 1) OG image
    og = meta_content(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']')
    u = norm_and_filter(og)
    if u:
        return u

    # 2) Twitter image
    tw = meta_content(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']')
    u = norm_and_filter(tw)
    if u:
        return u

    # 3) JSON-LD
    for m in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    ):
        raw = (m.group(1) or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        candidates: list[dict] = []
        if isinstance(data, dict):
            g = data.get("@graph")
            if isinstance(g, list):
                candidates = [x for x in g if isinstance(x, dict)]
            else:
                candidates = [data]
        elif isinstance(data, list):
            candidates = [x for x in data if isinstance(x, dict)]

        for item in candidates:
            t = item.get("@type")
            types: list[str] = []
            if isinstance(t, str):
                types = [t]
            elif isinstance(t, list):
                types = [x for x in t if isinstance(x, str)]
            if types and not any(x in ("NewsArticle", "Article") for x in types):
                continue

            img = item.get("image")
            raw_candidates: list[str] = []
            if isinstance(img, str):
                raw_candidates = [img]
            elif isinstance(img, list):
                for x in img:
                    if isinstance(x, str):
                        raw_candidates.append(x)
                    elif isinstance(x, dict):
                        u0 = x.get("url")
                        if isinstance(u0, str):
                            raw_candidates.append(u0)
            elif isinstance(img, dict):
                u0 = img.get("url")
                if isinstance(u0, str):
                    raw_candidates = [u0]

            for ru in raw_candidates:
                u = norm_and_filter(ru)
                if u:
                    return u

    return None


def fetch_article_image_url(
    session: requests.Session, url: str, timeout: tuple, strict: bool = True
) -> str | None:
    """
    Fetch article HTML and extract a hero image URL. Returns None on failure.
    Kept separate from fetch_article_body to avoid changing summarization behavior.
    """
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
        }
        resp = session.get(url, timeout=timeout, headers=headers)
        resp.raise_for_status()
        page_html = _html_text(resp)
        return extract_article_image_url(page_html, url, strict=strict)
    except Exception as e:
        log.info("No image extracted for %s (%s)", url, e)
        return None
