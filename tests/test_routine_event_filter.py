from config import should_skip_routine_football_event


def test_skips_routine_tarczynski_arena_football_fixture():
    assert should_skip_routine_football_event(
        "Mecz Śląsk Wrocław vs Wieczysta Kraków | 25.10.2026",
        "https://tarczynskiarenawroclaw.pl/events/mecz-slask-wroclaw-vs-wieczysta-krakow-25-10-2026/",
    )


def test_does_not_skip_unrelated_article_url():
    assert not should_skip_routine_football_event(
        "City announces transport changes for match day",
        "https://www.wroclaw.pl/komunikacja/transport-changes",
    )


def test_does_not_skip_other_arena_event():
    assert not should_skip_routine_football_event(
        "NightWave running event",
        "https://tarczynskiarenawroclaw.pl/events/nightwave-2026/",
    )
