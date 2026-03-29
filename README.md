# Singapore Condo Price Tracker

Interactive dashboard for analysing Singapore private residential property transactions using data from the URA Data Service API.

**Live demo:** https://singaporeproperty20-26.netlify.app

---

## What it shows

- PSF price trends (2021–2026) by bedroom type
- Freehold vs Leasehold price comparison
- Transaction volume by tenure, district, and bedroom
- Top projects by average PSF
- Filters: district, bedroom type, size band, year, month, tenure, project

---

## Files

| File | Description |
|------|-------------|
| `Netlify upload_property/index.html` | Main dashboard — open this in a browser |
| `House/sg-condo-dashboard.html` | Alternate version of the dashboard |
| `House/price-gap-dashboard.html` | Price gap analysis dashboard |
| `fetch_ura_data.py` | Script to pull fresh data from URA API |
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
