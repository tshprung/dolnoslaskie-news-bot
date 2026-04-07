from config import LISTICLE_TITLE_SKIP


def test_listicle_title_skip_matches_obvious_quiz():
    assert LISTICLE_TITLE_SKIP.search("Osoby o tym imieniu piją najwięcej alkoholu. Kto na liście?")


def test_listicle_title_skip_matches_tak_teraz_wygladaja():
    assert LISTICLE_TITLE_SKIP.search("Tak teraz wyglądają miejsca, w których kręcono film.")


def test_listicle_title_skip_does_not_match_hard_news():
    assert not LISTICLE_TITLE_SKIP.search("Atak na kontrolerkę MPK we Wrocławiu. Policja szuka sprawcy")

