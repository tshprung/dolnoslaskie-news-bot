from scrape_sources import (
    canonical_walbrzych24_article_url,
    extract_24wroclaw_items,
    extract_echo24_items,
    extract_walbrzych24_items,
)


def test_extract_24wroclaw_items_basic():
    html = """
    <html><body>
      <a href="/artykul/test-1-n123">Pierwszy tytuł we Wrocławiu</a>
      <a href="/artykul/test-2-n124">Drugi tytuł w regionie</a>
      <a href="/inne">ignore</a>
    </body></html>
    """
    items = extract_24wroclaw_items(html, base_url="https://24wroclaw.pl/")
    urls = [it.url for it in items]
    assert "https://24wroclaw.pl/artykul/test-1-n123" in urls
    assert "https://24wroclaw.pl/artykul/test-2-n124" in urls


def test_extract_echo24_items_basic():
    html = """
    <html><body>
      <a href="/pl/11_wiadomosci/94227_takiego-kalendarza-na-dolnym-slasku-nie-bylo.html">Takiego kalendarza na Dolnym Śląsku nie było</a>
      <a href="/pl/13_sport/99999_sport.html">Sport</a>
    </body></html>
    """
    items = extract_echo24_items(html, base_url="https://echo24.tv/")
    assert len(items) == 1
    assert items[0].url == "https://echo24.tv/pl/11_wiadomosci/94227_takiego-kalendarza-na-dolnym-slasku-nie-bylo.html"
    assert "kalendarza" in items[0].title.lower()


def test_extract_echo24_items_accepts_absolute_href():
    html = """
    <html><body>
      <a href="https://echo24.tv/pl/11_wiadomosci/94224_wielka-budowa-w-sercu-wroclawia.html?x=1">Wielka budowa w sercu Wrocławia</a>
    </body></html>
    """
    items = extract_echo24_items(html, base_url="https://echo24.tv/")
    assert len(items) == 1
    assert items[0].url == "https://echo24.tv/pl/11_wiadomosci/94224_wielka-budowa-w-sercu-wroclawia.html"


def test_canonical_walbrzych24_article_url_collapses_k_variants():
    a = canonical_walbrzych24_article_url(
        "https://www.walbrzych24.com/artykul/51682/k/1/mandat-albo-pierwsza-pomoc"
    )
    b = canonical_walbrzych24_article_url(
        "https://www.walbrzych24.com/artykul/51682/k/17/mandat-albo-pierwsza-pomoc"
    )
    assert a == b == "https://walbrzych24.com/artykul/51682/mandat-albo-pierwsza-pomoc"


def test_extract_walbrzych24_items_basic():
    html = """
    <html><body>
      <a href="/artykul/51689/k/1/po-premierze-ksiazki">Po premierze książki w Wałbrzychu</a>
      <a href="/artykul/51647/zajecia-gordonowskie-w-walbrzychu">Zajęcia gordonowskie w Wałbrzychu</a>
      <a href="/kategoria/31">Kategoria</a>
    </body></html>
    """
    items = extract_walbrzych24_items(html, base_url="https://www.walbrzych24.com/")
    urls = [it.url for it in items]
    assert "https://walbrzych24.com/artykul/51689/po-premierze-ksiazki" in urls
    assert "https://walbrzych24.com/artykul/51647/zajecia-gordonowskie-w-walbrzychu" in urls
    assert len(urls) == len(set(urls))

