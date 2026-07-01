# Portugal vs Croatia ticket watcher

Checks StubHub, SeatGeek and Vivid Seats every 5 minutes for the
**Portugal vs Croatia** FIFA World Cup match (BMO Field, Toronto, Jul 2 2026,
7:00 PM) and **emails you + your friends a status update on every check**,
clearly marked as either still above or at/below the **$2,200 CAD (incl.
fees/taxes)** cutoff.

Prices are converted to CAD automatically if a site is showing USD (these
`.com` sites default to USD pricing from a US-based IP, which is what GitHub
Actions runners have) - see "Currency handling" below.

Runs automatically every 5 minutes via an external cron trigger
(cron-job.org) hitting the GitHub Actions `workflow_dispatch` API - this is
more reliable than GitHub's native `schedule:` trigger, which can take a
long time to activate for a brand-new workflow. The `schedule:` trigger in
`.github/workflows/ticket-watch.yml` is left in as a redundant backup.
Nothing needs to stay open on your machine either way.

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

## Currency handling

StubHub/SeatGeek/Vivid Seats are `.com` sites with no separate Canadian
domain, and they determine currency from the request's IP address, not
just browser locale - so from a US-hosted GitHub Actions runner they
typically show **USD**. The scraper detects the actual currency shown per
site (from the page's embedded data, or by counting CAD/USD mentions) and
converts USD to CAD (`USD_TO_CAD_RATE`, default 1.38, approximate - not a
live rate) before comparing to the threshold. The email shows both the
native price and the converted CAD price whenever a conversion was applied.
If a site's currency can't be determined at all, its prices are dropped
rather than risk mislabeling them.

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
