from summarize import (
    _mentions_major_israeli_city,
    _source_suggests_germany_domestic_not_israel,
)


def test_berlin_source_flags_tel_aviv_text():
    de = "Demonstration am Brandenburger Tor in Berlin"
    he = "Discussion in Tel Aviv about a local case."
    assert _source_suggests_germany_domestic_not_israel(de) is True
    assert _mentions_major_israeli_city(he) is True


def test_israel_story_in_german_not_flagged_as_germany_domestic_only():
    de = "Deutsche Botschaft in Israel Tel Aviv"
    assert _source_suggests_germany_domestic_not_israel(de) is False


def test_koeln_triggers_germany_domestic_guard():
    de = "Karneval in Köln"
    assert _source_suggests_germany_domestic_not_israel(de) is True


def test_sachsen_anhalt_klinikum_triggers_germany_domestic():
    de = (
        "Kliniken in Sachsen-Anhalt setzen bei Sprachbarrieren auf Dolmetschdienste; "
        "Klinikum Saalekreis."
    )
    assert _source_suggests_germany_domestic_not_israel(de) is True