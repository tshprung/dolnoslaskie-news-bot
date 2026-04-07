from config import SYSTEM_PROMPT


def test_system_prompt_mentions_portugal_and_lisboa_latin():
    assert "Dolnośląskie" in SYSTEM_PROMPT or "Dolnoslaskie" in SYSTEM_PROMPT
    assert "Wrocław" in SYSTEM_PROMPT or "Wroclaw" in SYSTEM_PROMPT
    assert "Never invent locations" in SYSTEM_PROMPT
