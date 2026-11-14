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

For a **public** repo you can also bootstrap with a normal `git clone` into `/opt/dolnoslaskie_news`; for **private** repos the Action (or a VM deploy key) handles auth.

## 5. Cron

The bot is designed to run frequently so RSS sources are checked promptly. Non-RSS listing sources remain hourly-gated internally, so increasing cron frequency does not increase their scrape frequency.

```bash
crontab -e
```

Recommended schedule (every 30 minutes, on the **:20** and **:50** of each hour — avoids clashing with top-of-hour jobs):

```cron
CRON_TZ=Europe/Warsaw
20,50 * * * * /opt/dolnoslaskie_news/run.sh
5,35 * * * * /opt/dolnoslaskie_news/run_digest.sh
```

The normal delivery mode is a **daily digest**, controlled by:

```env
NEWS_DIGEST_ENABLED=1
NEWS_DIGEST_HOUR=19
NEWS_DIGEST_MAX_ITEMS=10
```

The digest is sent on the first delivery run at or after the configured hour. The independent delivery schedule above also retries a failed send every 30 minutes. Separate locks allow delivery while collection is still running. Both commands load `.env` and use a watchdog.

`run.sh` collects stories and then invokes `run_digest.sh` as a fallback even if collection fails or times out. Existing cron installations therefore keep delivering after an upgrade, but add the second line above to keep delivery independent of slow collection. A separate delivery lock and a per-day database record prevent simultaneous scheduled runs from sending the same brief.

For manual operation, use `python main.py --mode collect` or `python main.py --mode digest`. With no arguments, `main.py` retains its collect-then-deliver behavior. Accepted stories are queued in SQLite and are not posted individually.

**Important:** this means changing cron to every 30 minutes improves collection freshness, but it does **not** create 30-minute Telegram notifications. The user still receives one daily brief.

**Weekly community message** (English intro + support link): `run_weekly_announce.sh` posts **once per ISO week** when the script runs in the configured window (default **Sunday 18:00** `Europe/Warsaw`). Use a **second** cron line with `CRON_TZ` so the hour matches Warsaw even if the server is UTC:

```cron
CRON_TZ=Europe/Warsaw
0 18 * * 0 /opt/dolnoslaskie_news/run_weekly_announce.sh
```

After deploy: `chmod +x /opt/dolnoslaskie_news/run_weekly_announce.sh`. Tune with `WEEKLY_ANNOUNCE_*` in `.env` (see `.env.example`); set `WEEKLY_ANNOUNCE_ENABLED=0` to turn off.

Logs: `/opt/dolnoslaskie_news/bot.log`.

### Upgrading and checking delivery

The workflow runs Python tests and shell syntax checks for pull requests and pushes. Deployment runs only for a successful push to `main`, and checks out the tested commit. The PR itself does not change the running VM.

Back up SQLite before upgrading, for example with `sqlite3 /opt/dolnoslaskie_news/seen.db ".backup '/opt/dolnoslaskie_news/seen-before-reliability.db'"`. The first run performs an additive migration. Pending stories are preserved. Historical rows already marked digested are migrated as published because older versions did not record which stories were actually sent; their true publication status cannot be reconstructed automatically.

New queue states are `pending`, `published`, `excluded`, and `expired`. Only published rows receive `digested_at` and appear in recent coverage history. Articles considered but declined by the editor are excluded. Selected articles removed for Telegram length, and articles outside the 60-item scan, remain pending. Pending stories expire 48 hours after publication. An empty queue or a legitimate empty editor selection does not close delivery for the day, allowing later useful stories to be sent.

Exact ID/URL deduplication remains in collection. Related reports are now compared by the final editor, with the newest reports first and prior published facts included as context. This preserves material updates but may increase summarization calls compared with the old aggressive lexical filter; watch token usage after rollout.

Missing publication dates and temporary body-fetch failures are retried up to three times, 30 minutes apart. They are recorded in `article_retries` rather than the year-long stale-URL cache. Confirmed old stories still use the stale cache. Exhausted retries are logged for inspection. Previously cached unknown-date failures cannot be distinguished from confirmed old stories; investigate individual URLs rather than clearing the whole stale cache.

Useful health signals in `bot.log` include `RSS source`, `Article retry`, `Daily digest sent`, and `OpenAI usage`. The last includes actual reported token counts by stage. Delivery exceptions exit nonzero so an external scheduler can alert. To check the latest successful brief:

```bash
sqlite3 /opt/dolnoslaskie_news/seen.db "SELECT v FROM bot_kv WHERE k='daily_digest_date';"
sqlite3 /opt/dolnoslaskie_news/seen.db "SELECT status,count(*) FROM digest_articles GROUP BY status;"
```

Configure your VM monitoring to alert if no successful brief appears after the expected delivery window, or if all RSS sources fail. Empty news days can be legitimate; use source health to distinguish quiet coverage from collection failure. Telegram delivery and SQLite cannot share a transaction: a process killed after Telegram accepts a message but before SQLite commits can still cause a repeat. Automatic HTTP retries are disabled for Telegram POSTs to avoid blindly replaying ambiguous sends.

## 6. OpenAI

Reuse the same **OpenAI** account/key as the Polish bot or a dedicated key — set `OPENAI_API_KEY` in `.env`.

## 7. Feeds

RSS list is in `config.py` (`FEEDS`). If a feed 404s or blocks your IP, remove or replace it.

### Production audit: October 2026

The VM's October 25–28 logs showed 32–55 candidate-processing attempts per day and 12–27 stories queued. They also showed repeated HTTP 403 responses from TuWrocław and all three listing sources. Local desktop access did not reproduce those blocks. Access denials now back off for 24 hours; no challenge bypass or proxy is used. Wałbrzych24 extraction supports its new `/pl/11_wiadomosci/` layout when access is available.

The frozen Nasze Miasto category feed has been replaced with regional feeds from Legnica.NET, Świdnica24 and Jelonka, all checked from the VM. Listing intake limits are per source. English summaries retain Polish place names without being rejected solely for containing several accented letters.

Before publication, short-lived traffic/water/power incident reports are fetched again and verified against the Warsaw delivery time. Superseded source paragraphs are removed. Resolved incidents expire; unknown status, inaccessible articles and verification failures remain pending and are omitted from the current brief. Successful verification replaces the cached summary. This adds a small verification API cost, with a bounded time budget, without sending extra Telegram messages.

Short-lived traffic alerts older than six hours and water/power/sewage alerts older than twelve hours expire before verification. A fresh fetch alone cannot prove an old event is ongoing. Prolonged disruptions need a fresh report; planned works and lasting policy decisions are not subject to these incident windows.

Source checks and unique candidate outcomes are now persisted in SQLite. With `.env` loaded, inspect them using:

```bash
venv/bin/python diagnostics.py --days 7
```

The report shows the latest source response, stale feeds, candidates, readable bodies, retries, rejected stories and queue outcomes. Candidate stages count each URL once; historical rejected-candidate details from before instrumentation cannot be reconstructed completely. Source checks are retained for 30 days.

### Editorial audit: November 2026

The November 3–6 review found 357 candidates and 220 queued stories, with repeated reports despite sufficient supply. Delivery now compares publisher article IDs as well as URLs (including PortalSamorzadowy headline/slug changes), using up to 80 published stories from the last seven days. A separate JSON novelty audit checks the selected stories against previously covered facts and against one another; a new publication date alone is not a material update. Reopenings and weather warnings with different validity periods remain eligible. Incomplete or failed novelty audits leave the queue and delivery marker untouched so cron can retry. This audit uses one bounded GPT-4o call (30-second timeout, no internal retries, temperature zero) when there is recent coverage or more than one selected candidate.

Explicit region-wide fog-warning date/time periods are compared deterministically: a different period is a new update, while the same period appears only once across history and the selected brief. Ambiguous warning periods remain subject to the editorial audit.

The November 14 recurrence of PortalSamorządowy article 682515 exposed a gap: the original article had aged out of the seven-day history. The bot now checks publisher identities against all retained published rows before incident verification, independently of the model's recent history (up to 120 stories over 21 days). A meaningful update should come from a distinct report. Keep published rows when maintaining the database; they are the record used for exact deduplication. Editorial ranking favors a varied brief, weaker recurring traffic and publicity items can be omitted, and a shorter edition is fine.

The editorial audience covers the whole województwo. Rank tangible benefits, eligibility, deadlines, consultations and service changes above generic city publicity and recaps, without geographic quotas. Summary/headline instructions preserve intent versus approval, readiness versus deployment, expansions versus new facilities, and project/component costs. Summaries now receive up to 6,000 characters by default (8,000 for qualifying long bodies) to retain later qualifications, increasing token use. Overlong summaries and summaries that omit the preliminary status of an intent resolution receive one repair attempt and must still pass language, length and intent-status checks.

Radio Wrocław, Jelonka and Świdnica24 use observed article-body containers rather than page-wide paragraph extraction. Comments, related stories, audio-player notices and advertising containers are excluded. Keep a small labelled sample of real source articles to evaluate these boundaries and rerun it when publisher layouts change. Include a school-merger intent resolution, renamed train-cancellation article, cross-publisher bypass-opening repeat, reopening, new weather-warning period and useful regional assistance announcement.

