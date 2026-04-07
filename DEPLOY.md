# Portugal news bot — manual setup

## 1. GitHub

1. Create an empty repo (e.g. **portugal-news-bot**).
2. **Repository → Settings → Secrets and variables → Actions** — add the same secrets you use for the Polish bot (or new deploy user):
   - `VM_HOST` — server hostname or IP  
   - `VM_USER` — SSH user (e.g. `ubuntu`, `debian`)  
   - `VM_SSH_KEY` — private key (full PEM) that can log in as `VM_USER`  

Optional: instead of the token in the workflow, you can use a **Deploy key** on the VM and `git@github.com:tshprung/portugal-news-bot.git` in the script; the current workflow uses `github.token` over HTTPS so you do not need that for a normal setup.

## 2. Telegram

1. **@BotFather** → `/newbot` → copy **HTTP API token** → `TELEGRAM_BOT_TOKEN` in `.env`.
2. Create the **channel** (Portugal news), add your bot as **admin** with **Post messages**.
3. Channel ID: forward a channel post to **@userinfobot** / **@getidsbot**, or use Bot API `getUpdates` after a test post. Typical format: `-100xxxxxxxxxx` → `TELEGRAM_CHANNEL_ID`.
4. Optional: your user id for skip notifications → `ADMIN_TELEGRAM_ID`.

## 3. Private repo + deploy

GitHub Actions SSHs into your VM and runs `git clone` / `git pull` there. **HTTPS clone needs credentials** — the workflow uses the automatic **`github.token`** (no extra secret) so the VM can pull this repository, including when it is **private**.

If an earlier deploy left a **broken** `/opt/portugal_news` (e.g. empty dir or failed clone), remove it once and re-run the workflow:

```bash
sudo rm -rf /opt/portugal_news
```

Then push to `main` again (or re-run the failed workflow job).

---

## 4. VM (first-time)

1. Merge the deploy workflow to `main` and let the Action run (or re-run the job). It creates `/opt/german_news`, clones with `github.token`, installs Python deps.
2. SSH in and add secrets file:

```bash
cd /opt/portugal_news
cp .env.example .env
nano .env   # TELEGRAM_*, OPENAI_API_KEY, DB_PATH=/opt/portugal_news/seen.db
chmod +x run.sh
```

For a **public** repo you can still bootstrap with a normal `git clone` into `/opt/german_news`; for **private** repos the Action (or a VM deploy key) handles auth.

## 5. Cron

```bash
crontab -e
```

Example (every 5 minutes; offset from Polish bot if you like):

```cron
*/5 * * * * /opt/portugal_news/run.sh
```

**Weekly community message** (Hebrew intro + support link): `run_weekly_announce.sh` posts **once per ISO week** when the script runs in the configured window (default **Sunday 18:00** `Europe/Warsaw`). Use a **second** cron line with `CRON_TZ` so the hour matches Warsaw even if the server is UTC:

```cron
CRON_TZ=Europe/Warsaw
0 18 * * 0 /opt/portugal_news/run_weekly_announce.sh
```

After deploy: `chmod +x /opt/portugal_news/run_weekly_announce.sh`. Tune with `WEEKLY_ANNOUNCE_*` in `.env` (see `.env.example`); set `WEEKLY_ANNOUNCE_ENABLED=0` to turn off.

Logs: `/opt/portugal_news/bot.log`.

## 6. OpenAI

Reuse the same **OpenAI** account/key as the Polish bot or a dedicated key — set `OPENAI_API_KEY` in `.env`.

## 7. Feeds

RSS list is in `config.py` (`FEEDS`). If a feed 404s or blocks your IP, remove or replace it. Some Portuguese outlets may serve teaser-only or paywalled HTML; the bot logs skip reasons such as *insufficient text (paywall/teaser/login…)* when there is not enough free text to summarize.
