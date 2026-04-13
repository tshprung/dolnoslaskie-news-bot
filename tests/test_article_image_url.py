"""extract_article_image_url — OG / Twitter / JSON-LD + safety filters (no network)."""

from article_fetch import extract_article_image_url


def test_og_image_same_host():
    html = """
    <html><head>
    <meta property="og:image" content="https://www.wroclaw.pl/media/hero.jpg" />
    </head></html>
    """
    u = extract_article_image_url(
        html, "https://www.wroclaw.pl/aktualnosci/a", strict=True
    )
    assert u == "https://www.wroclaw.pl/media/hero.jpg"


def test_twitter_image_used_when_og_missing():
    html = """
    <meta name="twitter:image" content="https://tuwroclaw.com/uploads/x.png" />
    """
    u = extract_article_image_url(
        html, "https://tuwroclaw.com/news/1", strict=True
    )
    assert u == "https://tuwroclaw.com/uploads/x.png"


def test_json_ld_newsarticle_image_string():
    html = r"""
    <script type="application/ld+json">
    {"@type":"NewsArticle","headline":"x","image":"https://echo24.tv/pl/img/z.jpg"}
    </script>
    """
    u = extract_article_image_url(
        html, "https://echo24.tv/pl/11_wiadomosci/1_x.html", strict=True
    )
    assert u == "https://echo24.tv/pl/img/z.jpg"


def test_json_ld_image_array_object():
    html = r"""
    <script type="application/ld+json">
    {"@type":"Article","image":[{"url":"https://example.com/a/lead.jpg"}]}
    </script>
    """
    u = extract_article_image_url(html, "https://example.com/post", strict=True)
    assert u == "https://example.com/a/lead.jpg"


def test_rejects_logo_path():
    html = """
    <meta property="og:image" content="https://www.wroclaw.pl/static/logo_main.png" />
    """
    assert (
        extract_article_image_url(html, "https://www.wroclaw.pl/x", strict=True) is None
    )


def test_rejects_cross_domain_strict():
    html = """
    <meta property="og:image" content="https://evil.example/steal.jpg" />
    """
    assert (
        extract_article_image_url(
            html, "https://www.wroclaw.pl/x", strict=True
        )
        is None
    )


def test_same_registrable_when_not_strict():
    html = """
    <meta property="og:image" content="https://i.wp.pl/a.jpg" />
    """
    u = extract_article_image_url(
        html, "https://wiadomosci.wp.pl/x", strict=False
    )
    assert u == "https://i.wp.pl/a.jpg"


def test_strict_rejects_cdn_different_registrable():
    html = """
    <meta property="og:image" content="https://i.wp.pl/a.jpg" />
    """
    assert (
        extract_article_image_url(
            html, "https://wiadomosci.wp.pl/x", strict=True
        )
        is None
    )


def test_rejects_http_only():
    html = """
    <meta property="og:image" content="http://www.wroclaw.pl/x.jpg" />
    """
    assert extract_article_image_url(html, "https://www.wroclaw.pl/x", strict=True) is None
