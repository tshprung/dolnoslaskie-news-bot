from datetime import datetime, timezone

from scrape_sources import parse_rss_datetime_string, rss_entry_published_utc


def test_parse_rss_datetime_string_portalsamorzadowy_format():
    dt = parse_rss_datetime_string("Tue, 24 Mar 2026 09:27:00")
    assert dt is not None
    assert dt.astimezone(timezone.utc).hour == 8
    assert dt.date().isoformat() == "2026-03-24"


def test_rss_entry_published_utc_prefers_published_not_updated():
    entry = {
        "published": "Tue, 24 Mar 2026 09:27:00",
        "published_parsed": None,
        "updated": "Tue, 16 Jun 2026 19:20:00",
        "updated_parsed": None,
    }
    dt = rss_entry_published_utc(entry)
    assert dt is not None
    assert dt.date().isoformat() == "2026-03-24"
