"""RSS excerpt: ZEIT-style empty description + content:encoded."""

from database import _entry_text_excerpt


def test_zeit_style_content_encoded_used_when_summary_empty():
    entry = {
        "summary": "",
        "content": [
            {
                "value": '<a href="https://www.zeit.de/x"><img src="y"></a> '
                "Das Museum in Rheinsberg ist umstritten. Der Streit geht weiter."
            }
        ],
    }
    ex = _entry_text_excerpt(entry)
    assert "Rheinsberg" in ex
    assert len(ex) >= 40


def test_content_none_placeholder_not_used():
    entry = {
        "summary": "",
        "content": [{"value": '<a href="x"><img></a> None'}],
    }
    ex = _entry_text_excerpt(entry)
    assert ex.lower() != "none"
