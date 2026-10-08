#!/usr/bin/env python3
"""
Grocery Deal Alert System
Fetches weekly ads from Publix, Kroger, and ALDI, matches them against
a personal shopping list, and emails the results.
"""

import os
import re
import csv
import smtplib
import logging
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
import anthropic
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
ANTHROPIC_MODEL   = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
ANTHROPIC_MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "2000"))

SMTP_HOST     = os.environ["SMTP_HOST"]
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.environ["SMTP_USER"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]
EMAIL_FROM    = os.getenv("EMAIL_FROM", SMTP_USER)
EMAIL_TO      = os.environ["EMAIL_TO"]   # comma-separated for multiple recipients

SHOPPING_LIST_PATH = os.getenv("SHOPPING_LIST_PATH", "shopping_list.csv")

STORES = {
    "Publix": {
        "index_url": "https://www.iheartpublix.com/category/weekly-ad/",
        "url_pattern": r"https://www\.iheartpublix\.com/\d{4}/\d{2}/publix-ad-coupons-[^\"]+",
        "deals_pattern": r"BOGOS[\s\S]+SAVE ON YOUR FAVORITES",
    },
    "Kroger": {
        "index_url": "https://www.iheartkroger.com/category/weekly-ad/",
        "url_pattern": r"https://www\.iheartkroger\.com/kroger-ad-coupons-[^\"]+",
        "deals_pattern": r"3 DAY SALE[\s\S]+?(?=About the Author|Leave a Reply|Comments)",
    },
    "ALDI": {
        "index_url": "https://www.aldireviewer.com/",
        "url_pattern": r"https://www\.aldireviewer\.com/this-week-at-aldi-[^\"]+",
        "deals_pattern": (
            r"Aldi does not offer online ordering for products after they sell out "
            r"at your local store\.([\s\S]+?)You can learn more about"
        ),
    },
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

# ---------------------------------------------------------------------------
# Shopping list
# ---------------------------------------------------------------------------

def load_shopping_list(path: str) -> str:
    """
    Load shopping list from CSV and return as a newline-separated string
    in Category / Subcategory / Brand / Size format.
    """
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            parts = [
                row.get("Category", "").strip(),
                row.get("Subcategory", "").strip(),
                row.get("Brand", "").strip(),
                row.get("Size", "").strip(),
            ]
            rows.append(" / ".join(parts))
    return "\n".join(rows)

# ---------------------------------------------------------------------------
# Ad fetching
# ---------------------------------------------------------------------------

def fetch_text(url: str) -> str:
    """Fetch a URL and return the raw text content."""
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def extract_article_url(index_html: str, pattern: str) -> str:
    """Extract the first matching article URL from an index page."""
    match = re.search(pattern, index_html)
    if not match:
        raise ValueError(f"No article URL found matching pattern: {pattern}")
    return match.group(0)


def strip_html(html: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_deals(text: str, pattern: str) -> str:
    """Extract the deals section from cleaned text using a regex pattern."""
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        log.warning("Deals pattern did not match — returning full text as fallback")
        return text
    # Return group 1 if the pattern has a capturing group, otherwise the full match
    return match.group(1) if match.lastindex else match.group(0)


def fetch_store_ad(store_name: str, config: dict) -> str:
    """
    Full pipeline for one store:
    fetch index → extract article URL → fetch article → strip HTML → extract deals
    """
    log.info(f"Fetching {store_name} index page...")
    index_html = fetch_text(config["index_url"])

    log.info(f"Extracting {store_name} article URL...")
    article_url = extract_article_url(index_html, config["url_pattern"])
    log.info(f"{store_name} article URL: {article_url}")

    log.info(f"Fetching {store_name} article...")
    article_html = fetch_text(article_url)

    log.info(f"Cleaning {store_name} content...")
    clean_text = strip_html(article_html)
    deals_text = extract_deals(clean_text, config["deals_pattern"])

    log.info(f"{store_name}: extracted {len(deals_text)} characters of deal content")
    return deals_text

# ---------------------------------------------------------------------------
# AI matching
# ---------------------------------------------------------------------------

PROMPT_TEMPLATE = """\
Today's date is {today}.

If any ad content appears more than 10 days old based on dates in
the text, add this line at the top of that store's results:
⚠️ WARNING: [store name] content may be outdated — verify manually.

You are a grocery deal assistant. Match the shopping list below
against this week's ad content from three stores.

SHOPPING LIST:
{shopping_list}

MATCHING RULES:
Each shopping list row has up to four fields: Category / Subcategory / Brand / Size
- Only filled-in fields must match — empty fields are wildcards
- If a Brand is specified, the ad item's brand must exactly match —
  do not match any other brand regardless of category
- If no Brand is specified, match any brand in that category
- All filled-in fields must match simultaneously — a partial match
  is not a match
- If the exact brand name does not appear verbatim in the ad text,
  do not report a match
- ALDI store brands (Reggano, Friendly Farms, Kirkwood, etc.) are
  not matches for name-brand requests

OUTPUT FORMAT:
One line per match:
STORE | ITEM | DEAL | [COUPON only if one exists, otherwise omit]

If nothing matches at a store:
[Store name] | nothing on your list this week

Do not include limits, notes, caveats, or explanations.
Do not include fields with no value.

PUBLIX AD:
{publix_ad}

KROGER AD:
{kroger_ad}

ALDI AD:
{aldi_ad}
"""


def find_deals(shopping_list: str, ads: dict[str, str]) -> str:
    """Send shopping list and ad content to Claude and return matched deals."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = PROMPT_TEMPLATE.format(
        today=datetime.now().strftime("%B %d, %Y"),
        shopping_list=shopping_list,
        publix_ad=ads.get("Publix", "No content retrieved."),
        kroger_ad=ads.get("Kroger", "No content retrieved."),
        aldi_ad=ads.get("ALDI", "No content retrieved."),
    )

    log.info("Sending prompt to Claude...")
    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=ANTHROPIC_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text

# ---------------------------------------------------------------------------
# Email delivery
# ---------------------------------------------------------------------------

def send_email(subject: str, body: str) -> None:
    """Send the deal alert email via SMTP."""
    msg = MIMEMultipart()
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    recipients = [addr.strip() for addr in EMAIL_TO.split(",")]

    log.info(f"Sending email to {recipients}...")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(EMAIL_FROM, recipients, msg.as_string())
    log.info("Email sent successfully.")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    today = datetime.now().strftime("%B %d, %Y")
    log.info(f"Grocery Deal Alert — {today}")

    # Load shopping list
    shopping_list = load_shopping_list(SHOPPING_LIST_PATH)
    log.info(f"Loaded {shopping_list.count(chr(10)) + 1} items from shopping list")

    # Fetch all store ads
    ads = {}
    for store_name, config in STORES.items():
        try:
            ads[store_name] = fetch_store_ad(store_name, config)
        except Exception as e:
            log.error(f"Failed to fetch {store_name} ad: {e}")
            ads[store_name] = f"Error retrieving {store_name} ad: {e}"

    # Match against shopping list
    results = find_deals(shopping_list, ads)

    # Send email
    subject = f"Weekly Grocery Deal Alert — {today}"
    send_email(subject, results)
    log.info("Done.")


if __name__ == "__main__":
    main()
