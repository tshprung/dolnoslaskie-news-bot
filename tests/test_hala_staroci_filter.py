from config import should_skip_hala_staroci_event


def test_skips_hala_stulecia_gielda_staroci_listing():
    assert should_skip_hala_staroci_event(
        "https://halastulecia.pl/wydarzenie/gielda-staroci-37"
    )


def test_does_not_skip_other_hala_stulecia_events():
    assert not should_skip_hala_staroci_event(
        "https://halastulecia.pl/wydarzenie/koncert-jazzowy"
    )


def test_does_not_skip_regular_news():
    assert not should_skip_hala_staroci_event(
        "https://www.wroclaw.pl/dla-mieszkanca/gielda-staroci-wroclaw-2026"
    )
