"""Regression: Dolnośląskie channel scope gates non-local wires."""

from config import CLASSIFY_PROMPT, SYSTEM_PROMPT


def test_classify_dolnoslaskie_local_channel():
    assert "SKIP" in CLASSIFY_PROMPT
    assert "Dolnośląskie" in CLASSIFY_PROMPT or "Dolnoslaskie" in CLASSIFY_PROMPT
    assert "local channel" in CLASSIFY_PROMPT


def test_system_dolnoslaskie_direct_tie():
    assert "Dolnośląskie" in SYSTEM_PROMPT or "Dolnoslaskie" in SYSTEM_PROMPT
    assert "SKIP" in SYSTEM_PROMPT


def test_system_nested_time_historical_quotes():
    assert "Nested time" in SYSTEM_PROMPT
    assert "2022" in SYSTEM_PROMPT or "earlier year" in SYSTEM_PROMPT
