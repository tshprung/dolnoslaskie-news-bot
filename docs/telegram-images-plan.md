# Dolnośląsk bot — Telegram images / preview plan (updated)

## Goal

Richer channel posts with a visual when the article has a suitable hero image, **without** pushing obvious commercial/ads creatives as channel “photos.”

## Done (ship as-is)

| Item | Detail |
|------|--------|
| **Native link preview** | `TELEGRAM_LINK_PREVIEW_ENABLED` (default on). Message includes the article URL as a **raw line** after the HTML link so Telegram can fetch Open Graph / page metadata and show the usual **preview card** (title + often image). |
| **`sendMessage` preview on** | `disable_web_page_preview: false` in `telegram_bot.py`. |

This path matches the earlier decision to prefer **Telegram’s built-in preview** over manually uploading images.

## Not implemented (optional future work)

Only needed if previews are **missing or wrong** for key outlets and you want **explicit** images.

| Step | Work |
|------|------|
| 1 | **`extract_article_image_url`**: parse `og:image`, Twitter `twitter:image`, JSON-LD `image` from HTML (reuse fetch session / timeout; cap size). |
| 2 | **Safety filters**: drop URLs that look like ads, trackers, sprites, data URIs, wrong hosts vs article domain, known promo patterns. |
| 3 | **`sendPhoto` path**: caption = same HTML as today (or plain fallback); on failure fall back to current `sendMessage`. |
| 4 | **Flags**: e.g. `TELEGRAM_IMAGES_ENABLED=0|1`, optional strict mode. Default off until filters are trusted. |
| 5 | **Tests**: fixtures for OG/Twitter/JSON-LD HTML; filter cases; mock Telegram `sendPhoto` payload. |

## Recommendation

- **Stay on link preview** until you see repeated gaps (no card, wrong image, paywall strips OG).  
- Add the **extract + `sendPhoto`** pipeline only if those gaps justify the extra code and review burden.

## Related files (current behaviour)

- `config.py` — `TELEGRAM_LINK_PREVIEW_ENABLED`  
- `main.py` — appends raw `article['link']` when flag is on  
- `telegram_bot.py` — `sendMessage` + preview not disabled  
