from config import should_skip_radio_wroc_ticker_title


def test_radio_wroc_aktualnosci_title_skipped():
    assert should_skip_radio_wroc_ticker_title(
        "Aktualności Radia Wrocław - najświeższe wiadomości"
    )


def test_plain_wro_article_not_skipped():
    assert not should_skip_radio_wroc_ticker_title(
        "Wrocław: nowe objazdy na Legnickiej po awarii"
    )
