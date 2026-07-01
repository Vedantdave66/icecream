"""
Portugal vs Croatia (FIFA World Cup, Match 83, BMO Field Toronto, Jul 2 2026)
ticket price watcher.

Checks StubHub, SeatGeek and Vivid Seats for the cheapest currently-listed
face-value tickets and emails a status update on every run, clearly marked
as either still above or at/below THRESHOLD_CAD.

This is a best-effort scraper. These marketplaces run bot-detection
(Cloudflare / PerimeterX / Akamai) that may block automated requests,
especially from cloud IP ranges like GitHub Actions runners. When a page is
blocked, no prices are extracted for that site and no email is sent -
we never alert on data we don't actually have.

Currency: these are .com sites that default to USD for US-based visitors,
and GitHub Actions runners are US-hosted. We set locale/timezone/geolocation
hints toward Toronto to nudge them into CAD, but that's not guaranteed - so
we also detect the currency actually shown on the page (from embedded JSON
currency codes, falling back to counting "CAD"/"USD" mentions) and convert
USD prices to CAD before comparing against the CAD threshold. Prices whose
currency can't be determined are dropped rather than guessed.
"""
import os
import re
import smtplib
import sys
from collections import Counter
from datetime import datetime, timezone
from email.mime.text import MIMEText

from playwright.sync_api import sync_playwright

EVENT_URLS = {
    "StubHub": "https://www.stubhub.com/world-cup-toronto-tickets-7-2-2026/event/153023856/",
    "SeatGeek": "https://seatgeek.com/fifa-world-cup-tickets/international-soccer/2026-07-02-7-pm/17234772",
    "Vivid Seats": "https://www.vividseats.com/world-cup-soccer-tickets-bmo-field-7-2-2026--sports-soccer/production/5080833",
}

THRESHOLD_CAD = float(os.environ.get("THRESHOLD_CAD", "2200"))
# Approximate USD->CAD rate used to convert prices found in USD. Update
# periodically - this is not a live FX lookup.
USD_TO_CAD_RATE = float(os.environ.get("USD_TO_CAD_RATE", "1.38"))

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
TORONTO_GEOLOCATION = {"latitude": 43.6532, "longitude": -79.3832}

# Matches JSON price fields like "price":{"amount":1234} or "totalPrice":1234.56
JSON_PRICE_RE = re.compile(
    r'"(?:price|listPrice|sellerAllInPrice|totalPrice|displayPrice)"\s*:\s*\{?\s*"?(?:amount|value)?"?\s*:?\s*(\d+(?:\.\d+)?)'
)
# Fallback: plain "$1,234" style amounts visible in rendered page text
DOLLAR_RE = re.compile(r"\$\s?([\d,]{3,7})(?:\.\d{2})?")
# Explicit currency codes embedded in JSON state, e.g. "currency":"CAD" or "currencyCode":"USD"
CURRENCY_CODE_RE = re.compile(r'"currency(?:Code)?"\s*:\s*"([A-Z]{3})"')


def detect_currency(html, body_text):
    codes = [c for c in CURRENCY_CODE_RE.findall(html) if c in ("USD", "CAD")]
    if codes:
        return Counter(codes).most_common(1)[0][0]
    usd_hits = body_text.count("USD") + body_text.count("US$")
    cad_hits = body_text.count("CAD") + body_text.count("C$")
    if cad_hits > usd_hits:
        return "CAD"
    if usd_hits > cad_hits:
        return "USD"
    return None


def fetch_prices(site, url, page):
    """Returns a list of (price_cad, native_price, native_currency) tuples."""
    results = []
    try:
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        html = page.content()
        body_text = page.inner_text("body")

        raw_prices = [float(m.group(1)) for m in JSON_PRICE_RE.finditer(html)]
        raw_prices = [v for v in raw_prices if 100 < v < 20000]
        if not raw_prices:
            raw_prices = [float(m.group(1).replace(",", "")) for m in DOLLAR_RE.finditer(body_text)]
            raw_prices = [v for v in raw_prices if 100 < v < 20000]
        raw_prices = sorted(set(raw_prices))

        currency = detect_currency(html, body_text)
        print(f"[{site}] page title: {page.title()!r}, extracted {len(raw_prices)} price points, "
              f"detected currency: {currency!r}")

        if currency is None and raw_prices:
            print(f"[{site}] could not determine currency (USD vs CAD) for the prices found - "
                  "dropping them rather than risk mislabeling.")
            return results

        for native_price in raw_prices:
            if currency == "USD":
                results.append((round(native_price * USD_TO_CAD_RATE, 2), native_price, "USD"))
            else:
                results.append((native_price, native_price, "CAD"))
    except Exception as e:
        print(f"[{site}] fetch failed: {e}", file=sys.stderr)
    return results


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
                      "(likely blocked by bot-detection, or the currency shown couldn't be "
                      "confirmed as CAD or USD) - nothing to report yet.")
    else:
        status = "AT OR BELOW" if combined <= THRESHOLD_CAD else "still ABOVE"
        lines += [
            f"Cheapest two tickets currently found are {status} the ${THRESHOLD_CAD:.0f} CAD "
            f"(fees + taxes included) cutoff:",
        ]
        for t in cheapest_two:
            if t["currency"] == "USD":
                lines.append(
                    f"  - ${t['native_price']:.2f} USD (~${t['price_cad']:.2f} CAD at "
                    f"~{USD_TO_CAD_RATE} rate) on {t['site']}"
                )
            else:
                lines.append(f"  - ${t['price_cad']:.2f} CAD on {t['site']}")
        lines.append(f"  - Combined: ${combined:.2f} CAD")
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
    elif combined <= THRESHOLD_CAD:
        subject = (f"Portugal vs Croatia tickets - AT/BELOW ${THRESHOLD_CAD:.0f} CAD cutoff! "
                    f"(${combined:.2f} CAD for 2, incl. fees/taxes)")
    else:
        subject = (f"Portugal vs Croatia tickets - status update: still ABOVE ${THRESHOLD_CAD:.0f} CAD cutoff "
                    f"(${combined:.2f} CAD for 2, incl. fees/taxes)")
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

    flat = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            locale="en-CA",
            timezone_id="America/Toronto",
            geolocation=TORONTO_GEOLOCATION,
            permissions=["geolocation"],
        )
        page = context.new_page()
        for site, url in EVENT_URLS.items():
            for price_cad, native_price, currency in fetch_prices(site, url, page):
                flat.append({
                    "price_cad": price_cad,
                    "native_price": native_price,
                    "currency": currency,
                    "site": site,
                })
        browser.close()

    flat.sort(key=lambda t: t["price_cad"])

    if len(flat) < 2:
        print(f"Only {len(flat)} usable CAD-equivalent price point(s) found across all sites this run "
              "(likely blocked by bot-detection, or currency undetermined) - need at least 2 to compare.")
        send_status_email(to_emails, None, None)
        print("Status email sent (no price data available).")
        return

    cheapest_two = flat[:2]
    combined = cheapest_two[0]["price_cad"] + cheapest_two[1]["price_cad"]
    print(f"Cheapest two: {cheapest_two}, combined=${combined:.2f} CAD, threshold=${THRESHOLD_CAD:.2f} CAD")

    send_status_email(to_emails, cheapest_two, combined)
    print("Status email sent.")


if __name__ == "__main__":
    main()
