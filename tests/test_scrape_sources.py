from scrape_sources import extract_24wroclaw_items, extract_echo24_items


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


def test_extract_echo24_drops_old_digest_links_under_wypadki():
    html = """
    <html><body>
      <a href="/pl/11_wiadomosci/94686_wroclawskie-kamienice.html">Wrocławskie kamienice nie do poznania</a>
      <h2>Wypadki – Dolny Śląsk</h2>
      <a href="/pl/11_wiadomosci/90501_stary-wypadek.html">Informacja o porwaniu i pościg</a>
      <a href="/pl/11_wiadomosci/90059_inny-stary-wypadek.html">Po śmiertelnym wypadku utrudnienia</a>
    </body></html>
    """
    items = extract_echo24_items(html, base_url="https://echo24.tv/")
    urls = [it.url for it in items]
    assert "https://echo24.tv/pl/11_wiadomosci/94686_wroclawskie-kamienice.html" in urls
    assert "https://echo24.tv/pl/11_wiadomosci/90501_stary-wypadek.html" not in urls
    assert "https://echo24.tv/pl/11_wiadomosci/90059_inny-stary-wypadek.html" not in urls


def test_extract_echo24_allows_fresh_post_section_item():
    html = """
    <html><body>
      <a href="/pl/11_wiadomosci/94610_aktualnosc.html">Świeży lead</a>
      <h2>Wypadki – Dolny Śląsk</h2>
      <a href="/pl/11_wiadomosci/94590_blisko-wypadku.html">Świeży wypadek w sekcji digest</a>
    </body></html>
    """
    items = extract_echo24_items(html, base_url="https://echo24.tv/")
    urls = [it.url for it in items]
    assert "https://echo24.tv/pl/11_wiadomosci/94610_aktualnosc.html" in urls
    assert "https://echo24.tv/pl/11_wiadomosci/94590_blisko-wypadku.html" in urls

