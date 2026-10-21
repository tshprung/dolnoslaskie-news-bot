"""Log actual token usage without logging article bodies or API credentials."""
import logging

log = logging.getLogger(__name__)


def complete(client, stage, **kwargs):
    response = client.chat.completions.create(**kwargs)
    usage = getattr(response, "usage", None)
    if usage is not None:
        log.info(
            "OpenAI usage: stage=%s model=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s",
            stage, kwargs.get("model"), getattr(usage, "prompt_tokens", None),
            getattr(usage, "completion_tokens", None), getattr(usage, "total_tokens", None),
        )
    return response
