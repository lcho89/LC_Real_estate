# Singapore Condo Price Tracker

Interactive dashboard for analysing Singapore private residential property transactions using data from the URA Data Service API.

**Live demo:** https://singaporeproperty20-26.netlify.app

---

## What it shows

- PSF price trends by bedroom type (full history returned by URA)
- Freehold vs Leasehold price comparison
- Transaction volume by tenure, district, and bedroom
- Top projects by average PSF
- Filters: district, bedroom type, size band, year, month, tenure, project

---

## Files

| File | Description |
|------|-------------|
| `index.html` | Main dashboard — open this in a browser |
| `dashboards/sg-condo-dashboard.html` | Alternate version of the dashboard |
| `dashboards/price-gap-dashboard.html` | Price gap analysis dashboard |
| `fetch_ura_data.py` | Script to pull fresh data from URA API (Python) |
| `Fetch-UraData.ps1` | Same fetch, native PowerShell — no Python needed (Windows) |
| `ura_data.js` | *(not in repo — generated locally, see below)* |

---

## How to load real data

The dashboard ships with synthetic sample data. To load ~126,000 real URA transactions:

### Step 1 — Register for a free URA API key

1. Go to https://eservice.ura.gov.sg/maps/api/
2. Click **Get Access** and register for a free account
3. You will receive an **Access Key** by email

### Step 2 — Generate a daily token

The URA API requires a fresh token each day. Generate one via:

```
GET https://eservice.ura.gov.sg/uraDataService/insertNewToken/v1
Headers: AccessKey: <your-access-key>
```

Or use the Python script — it will prompt you for both.

### Step 3 — Run the fetch script

**Windows (PowerShell) — no Python required:**

```powershell
.\Fetch-UraData.ps1 -Key YOUR_ACCESS_KEY
```

That is the whole thing: with only `-Key` it generates today's token itself, so
Step 2 above can be skipped. Pass `-Token` explicitly if you already have one.
Output is identical to the Python script's.

If PowerShell refuses to run the file, its execution policy is blocking local
scripts. Allow them for the current session only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

**macOS / Linux (Python):**

```bash
pip install requests
python fetch_ura_data.py
```

You will be prompted for your Access Key and Token. The script downloads ~126,000 transactions across 4 batches and saves them as `ura_data.js`.

Or pass credentials directly:

```bash
python fetch_ura_data.py --key YOUR_ACCESS_KEY --token YOUR_DAILY_TOKEN
```

Optional: specify output path:

```bash
python fetch_ura_data.py --key YOUR_KEY --token YOUR_TOKEN --out path/to/ura_data.js
```

### Step 4 — Open the dashboard

Place `ura_data.js` in the same folder as `index.html`, then open `index.html` in your browser. The real data loads automatically.

## Monthly refresh

URA publishes on a monthly cycle, so the dashboard is refreshed on the **1st of each month**.

A scheduled Claude routine fires at **09:00 SGT on the 1st** as a reminder. The fetch
itself cannot run unattended — the URA Access Key is not stored in this repo.

On Windows, the whole refresh is one command:

```powershell
.\Fetch-UraData.ps1 -Key YOUR_ACCESS_KEY
```

Elsewhere, generate a token first
(`GET https://eservice.ura.gov.sg/uraDataService/insertNewToken/v1` with header
`AccessKey: <your-key>`), then run
`python fetch_ura_data.py --key YOUR_KEY --token TODAYS_TOKEN`.

Either way, refresh `index.html` afterwards, or re-upload the folder to Netlify.

The dashboard tracks its own freshness: `fetch_ura_data.py` stamps the pull date into
`ura_data.js`, and the banner shows **"Data as of YYYY-MM-DD"**. Once the data is a month
or more old the banner adds an amber **"N months old — run fetch_ura_data.py to refresh"**
flag, so a missed refresh is visible on the dashboard itself.

The year coverage is derived from the data at load time — no year is hardcoded, so the
header range and the Year filter extend on their own as new transactions arrive.

---

### Deploying to Netlify

1. Run the fetch script to generate `ura_data.js`
2. Drag the folder containing both `index.html` and `ura_data.js` onto https://app.netlify.com/drop
3. Share the generated URL — anyone can view it without needing Python or an API key

---

## Data source

URA (Urban Redevelopment Authority) — Singapore
https://eservice.ura.gov.sg/maps/api/
Data covers private residential transactions (Condominium, Apartment, Executive Condominium).

API registration is free. A new token must be generated each day.

URA sits behind a web application firewall that rejects default tool user-agents
(plain `curl`, `requests`), returning an HTML block page instead of JSON. Both
fetch scripts send a browser user-agent to get through it.
