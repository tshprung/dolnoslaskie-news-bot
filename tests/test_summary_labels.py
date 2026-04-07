from summarize import strip_leading_summary_labels


def test_strip_ibrit_prefix():
    s = "עברית: שריפה ב-Cottbus נמשכת."
    assert strip_leading_summary_labels(s) == "שריפה ב-Cottbus נמשכת."


def test_strip_ibrit_dash_prefix():
    s = "עברית - ב-Nordrhein-Westfalen צפוי מזג אוויר בהיר."
    assert strip_leading_summary_labels(s).startswith("ב-Nordrhein-Westfalen")


def test_strip_hebrew_colon_multiline_stacked():
    s = "עברית: תרגום: הסתיים."
    assert strip_leading_summary_labels(s) == "הסתיים."


def test_strip_english_prefix():
    assert strip_leading_summary_labels("Hebrew: זה ניסוי.").startswith("זה")
