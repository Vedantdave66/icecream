"""
Portugal vs Croatia (FIFA World Cup, Match 83, BMO Field Toronto, Jul 2 2026)
ticket price watcher.

Checks StubHub, SeatGeek and Vivid Seats for the cheapest currently-listed
face-value tickets, and emails a heads-up when the combined price of the two
cheapest tickets found is at or below THRESHOLD_CAD.

This is a best-effort scraper. These marketplaces run bot-detection
(Cloudflare / PerimeterX / Akamai) that may block automated requests,
especially from cloud IP ranges like GitHub Actions runners. When a page is
blocked, no prices are extracted for that site and no email is sent -
we never alert on data we don't actually have.
"""
import json
import os
import re
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.text import MIMEText

from playwright.sync_api import sync_playwright

EVENT_URLS = {
    "StubHub": "https://www.stubhub.com/world-cup-toronto-tickets-7-2-2026/event/153023856/",
    "SeatGeek": "https://seatgeek.com/fifa-world-cup-tickets/international-soccer/2026-07-02-7-pm/17234772",
    "Vivid Seats": "https://www.vividseats.com/world-cup-soccer-tickets-bmo-field-7-2-2026--sports-soccer/production/5080833",
}

THRESHOLD_CAD = float(os.environ.get("THRESHOLD_CAD", "2200"))
STATE_FILE = os.environ.get("STATE_FILE", "state.json")
FORCE_SEND = os.environ.get("FORCE_SEND", "false").strip().lower() == "true"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# Matches JSON price fields like "price":{"amount":1234} or "totalPrice":1234.56
JSON_PRICE_RE = re.compile(
    r'"(?:price|listPrice|sellerAllInPrice|totalPrice|displayPrice)"\s*:\s*\{?\s*"?(?:amount|value)?"?\s*:?\s*(\d+(?:\.\d+)?)'
)
# Fallback: plain "$1,234" style amounts visible in rendered page text
DOLLAR_RE = re.compile(r"\$\s?([\d,]{3,7})(?:\.\d{2})?")


def fetch_prices(site, url, page):
    prices = []
    try:
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        html = page.content()

        for match in JSON_PRICE_RE.finditer(html):
            val = float(match.group(1))
            if 100 < val < 20000:
                prices.append(val)

        if not prices:
            body_text = page.inner_text("body")
            for match in DOLLAR_RE.finditer(body_text):
                val = float(match.group(1).replace(",", ""))
                if 100 < val < 20000:
                    prices.append(val)

        print(f"[{site}] page title: {page.title()!r}, extracted {len(prices)} price points")
    except Exception as e:
        print(f"[{site}] fetch failed: {e}", file=sys.stderr)
    return sorted(set(prices))


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_alert_price": None}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def build_status_lines(cheapest_two, combined):
    lines = [
        "Portugal vs Croatia - FIFA World Cup Match 83",
        "BMO Field, Toronto - Jul 2, 2026, 7:00 PM",
        "",
        f"Watching for two tickets with a combined face value (including fees and taxes, "
        f"i.e. the final all-in checkout price) at or below ${THRESHOLD_CAD:.0f} CAD.",
        "",
    ]
    if cheapest_two is None:
        lines.append("No usable prices could be extracted from any site on this check "
                      "(likely blocked by bot-detection) - nothing to report yet.")
    else:
        status = "AT OR BELOW" if combined <= THRESHOLD_CAD else "still ABOVE"
        lines += [
            f"Cheapest two tickets currently found are {status} the ${THRESHOLD_CAD:.0f} CAD "
            f"(fees + taxes included) cutoff:",
            f"  - ${cheapest_two[0][0]:.2f} CAD on {cheapest_two[0][1]}",
            f"  - ${cheapest_two[1][0]:.2f} CAD on {cheapest_two[1][1]}",
            f"  - Combined: ${combined:.2f} CAD",
        ]
    lines += [
        "",
        "Check availability / seat locations before buying - prices and inventory move fast:",
    ]
    for site, url in EVENT_URLS.items():
        lines.append(f"  {site}: {url}")
    lines.append("")
    lines.append(f"Checked at {datetime.now(timezone.utc).isoformat()} UTC")
    return lines


def send_status_email(to_emails, cheapest_two, combined):
    if cheapest_two is None:
        subject = "Portugal vs Croatia tickets - status update (no prices found this check)"
    else:
        subject = f"Portugal vs Croatia tickets - status update (${combined:.2f} CAD for 2, cutoff ${THRESHOLD_CAD:.0f} CAD incl. fees/taxes)"
    body = "\n".join(build_status_lines(cheapest_two, combined))
    send_email(subject, body, to_emails)


def send_email(subject, body, to_emails):
    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASS"]
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = ", ".join(to_emails)
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, to_emails, msg.as_string())


def main():
    to_emails = [e.strip() for e in os.environ.get("TO_EMAILS", "").split(",") if e.strip()]
    if not to_emails:
        print("No TO_EMAILS configured, exiting.", file=sys.stderr)
        return

    all_prices = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT, locale="en-CA")
        page = context.new_page()
        for site, url in EVENT_URLS.items():
            all_prices[site] = fetch_prices(site, url, page)
        browser.close()

    flat = sorted((price, site) for site, prices in all_prices.items() for price in prices)

    if len(flat) < 2:
        print(f"Only {len(flat)} price point(s) found across all sites this run "
              "(likely blocked by bot-detection) - need at least 2 to compare. No alert sent.")
        if FORCE_SEND:
            send_status_email(to_emails, None, None)
            print("Forced status email sent (no price data available).")
        return

    cheapest_two = flat[:2]
    combined = cheapest_two[0][0] + cheapest_two[1][0]
    print(f"Cheapest two: {cheapest_two}, combined=${combined:.2f} CAD, threshold=${THRESHOLD_CAD:.2f} CAD")

    if FORCE_SEND:
        send_status_email(to_emails, cheapest_two, combined)
        print("Forced status email sent.")
        return

    state = load_state()
    last_alert = state.get("last_alert_price")

    if combined > THRESHOLD_CAD:
        print("Combined price above threshold; no alert.")
        return

    if last_alert is not None and combined >= last_alert - 1:
        print("Already alerted at this price or lower; skipping duplicate email.")
        return

    subject = f"Portugal vs Croatia tickets found under ${THRESHOLD_CAD:.0f} CAD, incl. fees/taxes (${combined:.2f} for 2)"
    body = "\n".join(build_status_lines(cheapest_two, combined))

    send_email(subject, body, to_emails)
    state["last_alert_price"] = combined
    save_state(state)
    print("Alert email sent.")


if __name__ == "__main__":
    main()
