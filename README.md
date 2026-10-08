# Grocery Deal Alert — Python / GitHub Actions

Automatically checks weekly sale ads from **Publix**, **Kroger**, and **ALDI** every week, matches them against your personal shopping list, and emails you the results.

Built with Python and Claude AI. Runs on a schedule via GitHub Actions — no server required.

---

## How it works

1. **Load shopping list** — reads `shopping_list.csv` from the repo
2. **Scrape store ads** — fetches the current weekly ad from three fan-sites that publish plain-text versions of each store's circular
3. **Strip HTML & extract deals** — regex cleans the raw HTML down to just the deals section
4. **Ask Claude** — sends all three ad excerpts and the shopping list to Claude in a single prompt; Claude returns only the matching deals
5. **Email results** — sends the matches (or "nothing on your list this week") via SMTP

---

## Setup

### 1. Fork or clone this repo

```bash
git clone https://github.com/ashenroot/grocery-deal-finder-python.git
cd grocery-deal-alert
```

### 2. Edit your shopping list

Open `shopping_list.csv` and add the items you want to track. Columns:

| Column | Required | Notes |
|---|---|---|
| Category | Yes | e.g. `cheese`, `beef`, `pasta` |
| Subcategory | No | e.g. `ground` for coffee |
| Brand | No | If set, must match exactly — e.g. `Tillamook` |
| Size | No | e.g. `12 oz` |
| Notes | No | Human-readable notes, ignored by the script |

**Empty fields are wildcards.** If you leave Brand blank, any brand in that category qualifies.

```csv
Category,Subcategory,Brand,Size,Notes
cheese,,Tillamook,,
butter,,Kerrygold,,
pasta,,Carbe Diem,,
chips,,Tostitos,,
coffee,ground,,12 oz,
beef,,,,any beef on sale
```

### 3. Get an Anthropic API key

Sign up at [console.anthropic.com](https://console.anthropic.com) and create an API key.

> **Note on rate limits:** This script sends three large ad pages to Claude in a single request. Anthropic's free Tier 1 limit is 30,000 input tokens/minute, which this will likely exceed. Adding a small amount of credit ($5–$10) upgrades you to Tier 2 (90,000 tokens/minute), which is sufficient.

### 4. Set up Gmail App Password (recommended sender)

1. Enable 2-Step Verification on your Google account
2. Go to **My Account → Security → App Passwords**
3. Create an app password for "Mail" — copy the 16-character password

### 5. Configure GitHub Secrets

In your forked repo, go to **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret | Example | Required |
|---|---|---|
| `ANTHROPIC_API_KEY` | `sk-ant-...` | ✅ |
| `SMTP_HOST` | `smtp.gmail.com` | ✅ |
| `SMTP_PORT` | `587` | ✅ |
| `SMTP_USER` | `you@gmail.com` | ✅ |
| `SMTP_PASSWORD` | `abcd efgh ijkl mnop` | ✅ |
| `EMAIL_FROM` | `you@gmail.com` | ✅ |
| `EMAIL_TO` | `you@gmail.com,spouse@gmail.com` | ✅ |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | optional |
| `ANTHROPIC_MAX_TOKENS` | `4000` | optional |

`EMAIL_TO` accepts a comma-separated list for multiple recipients.

### 6. Enable GitHub Actions

Go to the **Actions** tab in your repo and enable workflows if prompted.

The workflow runs automatically every **Wednesday at 9 PM Eastern**. To test it immediately, click **Run workflow** from the Actions tab.

---

## Running locally

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and fill in the env file
cp .env.example .env
# edit .env with your real values

# Run
python main.py
```

---

## Customizing the schedule

Edit `.github/workflows/weekly_alert.yml` and change the cron expression:

```yaml
- cron: "0 1 * * 4"   # Wednesday 9 PM Eastern (Thu 01:00 UTC)
```

Use [crontab.guru](https://crontab.guru) to build a custom schedule.

---

## Adding or removing stores

The store configuration lives in `main.py` in the `STORES` dict. Each entry needs:

- `index_url` — the page that lists recent weekly ads
- `url_pattern` — regex to extract the current ad's URL from that page
- `deals_pattern` — regex to extract just the deals section from the article

The Claude prompt in `PROMPT_TEMPLATE` also references each store by name — update it if you add a store.

---

## File structure

```
grocery-deal-alert/
├── main.py                  # main script
├── shopping_list.csv        # your shopping list (edit this)
├── requirements.txt         # Python dependencies
├── .env.example             # environment variable template
└── .github/
    └── workflows/
        └── weekly_alert.yml # GitHub Actions schedule
```

---

## Related

- [grocery-deal-alert-make](https://github.com/ashenroot/grocery-deal-finder-make) — same workflow as a Make.com blueprint (no-code version)

---

## License

MIT
