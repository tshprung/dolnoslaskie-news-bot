from article_fetch import _article_body_from_dom, _article_body_from_dom_wroclaw


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


def test_wroclaw_dom_prefers_main_content_over_boilerplate():
    stripped = """
    <html><body>
      <article>
        <p>Bądź na bieżąco z Wrocławiem!</p>
        <p>Kliknij „obserwuj”.</p>
      </article>
      <main>
        <h1>Atak na kontrolerkę biletów MPK Wrocław</h1>
        <p>Policja szuka młodego mężczyzny. Opis zdarzenia i prośba o kontakt.</p>
        <p>Wrocław: do zdarzenia doszło w tramwaju. Świadkowie proszeni o zgłoszenia.</p>
      </main>
    </body></html>
    """
    text = _article_body_from_dom_wroclaw(stripped)
    assert "Atak na kontrolerkę" in text
    assert "Bądź na bieżąco" not in text
