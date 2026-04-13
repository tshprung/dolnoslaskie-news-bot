"""Telegram sendPhoto payload (mocked HTTP)."""

from unittest.mock import MagicMock

from telegram_bot import send_photo_to_telegram


def test_send_photo_posts_json_with_photo_url():
    session = MagicMock()
    resp = MagicMock()
    resp.json.return_value = {"ok": True}
    resp.raise_for_status = MagicMock()
    session.post.return_value = resp

    send_photo_to_telegram(
        session,
        "https://www.wroclaw.pl/media/x.jpg",
        "<b>Caption</b> and <a href=\"https://x\">link</a>",
        timeout=(1, 2),
    )

    session.post.assert_called_once()
    args, kwargs = session.post.call_args
    assert "sendPhoto" in args[0]
    body = kwargs.get("json") or {}
    assert body.get("photo") == "https://www.wroclaw.pl/media/x.jpg"
    assert body.get("parse_mode") == "HTML"
    assert "Caption" in (body.get("caption") or "")


def test_send_photo_truncates_long_caption():
    session = MagicMock()
    resp = MagicMock()
    resp.json.return_value = {"ok": True}
    resp.raise_for_status = MagicMock()
    session.post.return_value = resp

    long_cap = "a" * 2000
    send_photo_to_telegram(session, "https://example.com/p.jpg", long_cap)
    body = session.post.call_args.kwargs["json"]
    assert len(body["caption"]) <= 1024
