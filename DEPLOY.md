# Dolnośląskie news bot — manual setup

## 1. GitHub

1. Create an empty repo (e.g. **dolnoslaskie-news-bot**).
2. **Repository → Settings → Secrets and variables → Actions** — add the same secrets you use for the Polish bot (or new deploy user):
   - `VM_HOST` — server hostname or IP  
   - `VM_USER` — SSH user (e.g. `ubuntu`, `debian`)  
   - `VM_SSH_KEY` — private key (full PEM) that can log in as `VM_USER`

Optional: instead of the token in the workflow, you can use a **Deploy key** on the VM and `git@github.com:tshprung/dolnoslaskie-news-bot.git` in the script; the current workflow uses `github.token` over HTTPS so you do not need that for a normal setup.

## 2. Telegram

1. **@BotFather** → `/newbot` → copy **HTTP API token** → `TELEGRAM_BOT_TOKEN` in `.env`.
2. Create the **channel** (Dolnośląskie news), add your bot as **admin** with **Post messages**.
3. Channel ID: forward a channel post to **@userinfobot** / **@getidsbot**, or use Bot API `getUpdates` after a test post. Typical format: `-100xxxxxxxxxx` → `TELEGRAM_CHANNEL_ID`.
4. Optional: your user id for skip notifications → `ADMIN_TELEGRAM_ID`.

## 3. Private repo + deploy

GitHub Actions SSHs into your VM and runs `git clone` / `git pull` there. **HTTPS clone needs credentials** — the workflow uses the automatic **`github.token`** (no extra secret) so the VM can pull this repository, including when it is **private**.

If an earlier deploy left a **broken** `/opt/dolnoslaskie_news` (e.g. empty dir or failed clone), remove it once and re-run the workflow:

```bash
sudo rm -rf /opt/dolnoslaskie_news
```

Then push to `main` again (or re-run the failed workflow job).

---

## 4. VM (first-time)

1. Merge the deploy workflow to `main` and let the Action run (or re-run the job). It creates `/opt/dolnoslaskie_news`, clones with `github.token`, installs Python deps.
2. SSH in and add secrets file:

```bash
cd /opt/dolnoslaskie_news
cp .env.example .env
nano .env   # TELEGRAM_*, OPENAI_API_KEY, DB_PATH=/opt/dolnoslaskie_news/seen.db
chmod +x run.sh
```

For a **public** repo you can still bootstrap with a normal `git clone` into `/opt/german_news`; for **private** repos the Action (or a VM deploy key) handles auth.

## 5. Cron

The bot is designed to run frequently so RSS sources are checked promptly. Non-RSS listing sources remain hourly-gated internally, so increasing cron frequency does not increase their scrape frequency.

```bash
crontab -e
```

Recommended schedule (every 30 minutes, on the **:20** and **:50** of each hour — avoids clashing with top-of-hour jobs):

```cron
CRON_TZ=Europe/Warsaw
20,50 * * * * /opt/dolnoslaskie_news/run.sh
```

The normal delivery mode is a **daily digest**, controlled by:

```env
NEWS_DIGEST_ENABLED=1
NEWS_DIGEST_HOUR=19
NEWS_DIGEST_MAX_ITEMS=10
```

The digest is sent on the first run at or after the configured hour. Accepted stories are stored in SQLite until the daily brief is sent; they are not posted individually.

**Important:** this means changing cron to every 30 minutes improves collection freshness, but it does **not** create 30-minute Telegram notifications. The user still receives one daily brief.

**Weekly community message** (English intro + support link): `run_weekly_announce.sh` posts **once per ISO week** when the script runs in the configured window (default **Sunday 18:00** `Europe/Warsaw`). Use a **second** cron line with `CRON_TZ` so the hour matches Warsaw even if the server is UTC:

```cron
CRON_TZ=Europe/Warsaw
0 18 * * 0 /opt/dolnoslaskie_news/run_weekly_announce.sh
```

After deploy: `chmod +x /opt/dolnoslaskie_news/run_weekly_announce.sh`. Tune with `WEEKLY_ANNOUNCE_*` in `.env` (see `.env.example`); set `WEEKLY_ANNOUNCE_ENABLED=0` to turn off.

Logs: `/opt/dolnoslaskie_news/bot.log`.

## 6. OpenAI

Reuse the same **OpenAI** account/key as the Polish bot or a dedicated key — set `OPENAI_API_KEY` in `.env`.

## 7. Feeds

RSS list is in `config.py` (`FEEDS`). If a feed 404s or blocks your IP, remove or replace it.
