from summarize import strip_leading_summary_labels


def test_strip_english_colon_prefix():
    s = "English: Fire continues in Wrocław."
    assert strip_leading_summary_labels(s) == "Fire continues in Wrocław."


def test_strip_english_dash_prefix():
    s = "English - Clear weather expected in Wałbrzych."
    assert strip_leading_summary_labels(s).startswith("Clear weather")


def test_strip_summary_colon_multiline_stacked():
    s = "Summary: English: Done."
    assert strip_leading_summary_labels(s) == "Done."


def test_strip_english_prefix():
    assert strip_leading_summary_labels("Summary: This is a test.").startswith("This")
