from article_fetch import _trim_boilerplate


def test_polish_laboratory_reporting_survives_boilerplate_cleanup():
    text = 'Nowe laboratorium we Wrocławiu rozpocznie badania jakości wody dla mieszkańców.'
    assert _trim_boilerplate(text) == text
