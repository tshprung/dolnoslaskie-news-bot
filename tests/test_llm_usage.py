import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

from llm_util import complete


def test_completion_logs_reported_token_usage_and_preserves_response(caplog):
    response = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20, total_tokens=120))
    client = MagicMock()
    client.chat.completions.create.return_value = response
    with caplog.at_level(logging.INFO):
        assert complete(client, 'digest_selection', model='example-model', messages=[]) is response
    assert 'stage=digest_selection' in caplog.text
    assert 'total_tokens=120' in caplog.text
