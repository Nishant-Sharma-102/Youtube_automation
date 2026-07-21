# Documentary channel — Phase 1: topic research + intake

A cinematic AI documentary channel (English) covering **History, Mysteries,
Science & Space, and Alternate History**. This is Phase 1 only: research and
queue 10 fact-checked topic ideas per batch into a Google Sheet as `draft`, for
you to review and approve by hand. Deliberately separate from the kids and
Hindi-history pipelines — its own Sheet, worksheet, and creds.

## What `generate_topics.py` does

1. Reads existing topics from the Sheet (all statuses) for de-duplication.
2. Asks Claude (**web search enabled**) for 10 topics across the four pillars
   (targets: History 4 / Mysteries 2-3 / Science & Space 2 / Alternate History
   1-2), fact-checking each against reputable sources and favouring evergreen
   subjects over trends.
3. Writes the 10 accepted topics as `status=draft` rows — **not** auto-approved.
   You promote the ones you want scripted to `status=approved` yourself.
4. Logs every rejected/considered candidate (duplicate / failed fact-check /
   too trend-driven) to `logs/rejected_topics.log`.
5. Sends a phone-friendly summary via Telegram → email → stdout (first configured
   wins).

Sheet columns: `topic | pillar | script | scene_breakdown | status | scheduled_date | notes`

## Setup

```bash
pip install -r requirements.txt        # or reuse ../hindi-history/.venv
cp .env.example .env                   # fill in the values
```

- **Claude:** set `ANTHROPIC_API_KEY` (or rely on the repo-root `.env`).
- **Sheet:** create a spreadsheet, put its ID in `DOC_SHEET_ID`, and give access:
  - *Service account (recommended for cron):* set `GOOGLE_SERVICE_ACCOUNT_JSON`
    to the key path and **share the spreadsheet with its `client_email`** as
    Editor. The worksheet tab (`DOC_WORKSHEET`, default `documentary`) and header
    row are created automatically on first run.
  - *OAuth:* set `DOC_OAUTH_CLIENT_JSON` and mint a `token.json`.
- **Notifications (optional):** `TELEGRAM_DOC_BOT_TOKEN` + `TELEGRAM_DOC_CHAT_ID`,
  or SMTP (`DOC_SMTP_*` + `DOC_EMAIL_TO`).

**No creds yet?** It still runs: with no Sheet it uses a local mirror
(`data/topics_mirror.json`); with no Telegram/email it prints the summary. Good
for testing before wiring up Google.

## Run

```bash
python generate_topics.py            # full run: generate → write drafts → notify
python generate_topics.py --dry-run  # generate + display only, no writes/notify
```

## Scheduling (cadence)

**Recommendation: run every 2 weeks, not weekly.** Each run adds 10 drafts, but a
10-15 min documentary takes real production time downstream — you'll realistically
finish a few episodes per fortnight, and you only approve a subset of each batch.
Weekly generation (40 topics/month) would pile up drafts far faster than you can
produce them and increase Claude/web-search spend for no benefit. Bi-weekly keeps
a healthy, curated backlog of ~20 candidates/month to choose from without runaway.
Monthly also works if production is slower; bump to weekly only if you scale up
output. The pillar de-duplication means later batches automatically avoid
repeating earlier topics.

Cron example (service-account creds, every other Monday 08:00 UTC):

```cron
0 8 */14 * *  cd /home/user/Documents/agentic_ai/documentary && \
  ../hindi-history/.venv/bin/python generate_topics.py >> logs/run.log 2>&1
```

(`*/14` on day-of-month is an approximate fortnight; for an exact 2-week cadence
use a weekly cron guarded by an even/odd ISO-week check, or a scheduler that
supports intervals.)
