# Portugal vs Croatia ticket watcher

Checks StubHub, SeatGeek and Vivid Seats every 5 minutes for the
**Portugal vs Croatia** FIFA World Cup match (BMO Field, Toronto, Jul 2 2026,
7:00 PM) and emails you + your friends when the combined face value of the
two cheapest tickets it can find is **at or below $2,200 CAD**.

Runs automatically as a GitHub Actions scheduled workflow
(`.github/workflows/ticket-watch.yml`) - nothing needs to stay open on your
machine.

## Important limitation

StubHub/SeatGeek/Vivid Seats run bot-detection (Cloudflare, PerimeterX,
Akamai) that can block automated requests outright, and GitHub Actions'
shared IP ranges are commonly blacklisted by these systems. The scraper is
built to fail safe: if a page is blocked, it just finds 0 prices for that
site and skips alerting for that run - it will never email you fake or
guessed data. Check the Actions run logs (see below) to see whether it's
actually getting real prices or getting blocked.

If it's consistently blocked from GitHub Actions, the same script can be run
from your own computer instead (a residential IP has better odds), see
"Running locally" below.

## One-time setup

1. **Create a Gmail App Password** for `vedantdave9@gmail.com` (requires
   2-Step Verification to be turned on):
   - Go to https://myaccount.google.com/apppasswords
   - Create an app password named e.g. "ticket-watch", copy the 16-character
     code.

2. **Add repo secrets** (Settings -> Secrets and variables -> Actions -> New
   repository secret):
   - `SMTP_USER` = `vedantdave9@gmail.com`
   - `SMTP_PASS` = the app password from step 1
   - `TO_EMAILS` = `vedantdave9@gmail.com,gunjpatel@ymail.com` (comma
     separated - add a third address here later, no code change needed)

3. **Merge this branch to `main`.** GitHub only runs scheduled (`cron`)
   workflows from the default branch, so the 5-minute schedule won't fire
   until this is merged.

4. Confirm Actions is enabled for the repo (Settings -> Actions -> General).

Once merged, it checks every 5 minutes automatically. You can also trigger a
manual test run any time from the "Actions" tab -> "Portugal vs Croatia
Ticket Watch" -> "Run workflow".

## Turning it off

After the game (or once you've bought tickets), disable the workflow from
the Actions tab ("..." -> "Disable workflow") so it stops running.

## Running locally instead

If GitHub Actions gets consistently blocked, run the same checker from your
own machine, e.g. via `cron` (Mac/Linux) or Task Scheduler (Windows):

```bash
cd ticket_watch
pip install -r requirements.txt
playwright install chromium
export SMTP_USER=vedantdave9@gmail.com
export SMTP_PASS=your-app-password
export TO_EMAILS=vedantdave9@gmail.com,gunjpatel@ymail.com
python scraper.py
```

Add that as a cron job running every 5 minutes:

```
*/5 * * * * cd /path/to/ticket_watch && SMTP_USER=... SMTP_PASS=... TO_EMAILS=... /usr/bin/python3 scraper.py >> watch.log 2>&1
```
