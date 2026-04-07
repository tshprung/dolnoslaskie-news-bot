from article_fetch import _article_body_from_dom


def test_dom_does_not_replace_long_primary_with_few_short_paragraphs():
    body_inner = ("Satz mit Artikelinhalt. " * 120)
    stripped = f"""<html><body>
<div class="ods-article-body">
<div>{body_inner}</div>
<p>Kurzes Zitat.</p>
</div></body></html>"""
    text = _article_body_from_dom(stripped)
    assert len(text) > 2000
    assert "Artikelinhalt" in text
