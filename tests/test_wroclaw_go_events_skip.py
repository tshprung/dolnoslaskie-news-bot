from config import should_skip_wroclaw_go_event_url


def test_skips_wroclaw_go_teatr_event_url():
    url = (
        "https://www.wroclaw.pl/go/wydarzenia/teatr/"
        "1407046-czekajac-na-barbarzyncow-we-wroclawskim-teatrze-wspolczesnym"
    )
    assert should_skip_wroclaw_go_event_url(url)


def test_does_not_skip_normal_wroclaw_article_url():
    url = "https://www.wroclaw.pl/dla-mieszkanca/jakas-aktualnosc"
    assert not should_skip_wroclaw_go_event_url(url)
