from config import should_skip_wroclaw_go_event_url


def test_skips_guided_tour_event_listings():
    assert should_skip_wroclaw_go_event_url(
        "https://www.wroclaw.pl/go/wydarzenia/sport-i-rekreacja/1351403-mosty-i-wyspy-wroclawia-spacer-z-przewodnikiem-walkative"
    )
    assert should_skip_wroclaw_go_event_url(
        "https://www.wroclaw.pl/go/wydarzenia/sport-i-rekreacja/1393146-tajemnice-wroclawskiego-ratusza-wycieczka-z-przewodnikiem"
    )


def test_does_not_skip_regular_news_articles():
    assert not should_skip_wroclaw_go_event_url(
        "https://www.wroclaw.pl/komunikacja/changes-to-public-transport"
    )
