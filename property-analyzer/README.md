# Property Analyzer — Eric Chiew Framework

Decides whether a Singapore listing is **undervalued**, by benchmarking it against real URA
transactions and scoring it on Eric Chiew's three pillars: **Location · Entry Pricing · Exit
Strategy**, averaged into one figure out of 10.

Two ways to use it:

| | |
|---|---|
| **The app** — `index.html` | Paste a listing, get a verdict, comps table, fair-value ladder and price-trend chart. |
| **The skill** — `.claude/skills/property-analysis/` | Ask Claude directly: *"is this listing undervalued?"* It pulls live data, runs the same model, and writes the report. |

---

## Running the app

Serve the **repo root** over HTTP — `file://` will not load the dataset, and the app reaches up a
level for it.

```bash
python -m http.server 8082 --directory .
```

Then open http://localhost:8082/property-analyzer/. In Claude Code, the **Property Analyzer**
config in `.claude/launch.json` does the same thing.

### Monthly data refresh

The app keeps **no copy** of the data. On every load it HEAD-probes each known dataset and loads
whichever was **written most recently**:

- `../FetchURA/ura_data.js`
- `../Netlify upload_property/ura_data.js`
- `../House/ura_data.js`
- `./ura_data.js`

Refresh any one of them and the analyzer picks it up on the next reload — no path order to
maintain and nothing to copy. The banner names the file it chose, its age, and how many older
copies it ignored, and turns **red past 45 days** so a stale dataset can't quietly value a live
listing.

The sibling probes only run on localhost; a deployed bundle ships a single `ura_data.js`.

---

## Deploying

The app reaches up a directory for data, which no host allows, so bundle it first:

```bash
python property-analyzer/build.py
```

That writes `property-analyzer/dist/` — `index.html`, the freshest `ura_data.js`, and a
`vercel.json` with sensible cache headers. Then:

```bash
cd property-analyzer/dist && npx vercel deploy --prod
```

The first run prompts you to log in and name the project. `dist/` is gitignored and is a
**snapshot** — re-run `build.py` after each data refresh, then redeploy.

Netlify works the same way: `npx netlify deploy --prod --dir=property-analyzer/dist`.

Note the bundle is ~15 MB because of the dataset. That is well under Vercel's 100 MB static limit,
but it is a real download for a first-time visitor — the `Cache-Control` header in `vercel.json`
means they only pay it once a day.

### What it does

1. **Paste the listing** — the parser pulls project, price, size, bedrooms, baths, district,
   tenure, TOP year, unit count and floor out of raw listing text.
2. **Fill the gaps** — MRT distance, schools within 1 km and unit count are not in URA data.
   Get the first two from `location.py` (below).
3. **Analyse** — it builds the comps, runs the fair-value ladder, scores the three pillars and
   applies the hard-veto checklist.

### The fair-value ladder

Two modes, picked automatically:

- **Like-for-like** — the project already has 3+ transactions in the window. Baseline is the
  project's own median PSF, adjusted only for floor.
- **Benchmark ladder** — a new launch with no history. Pick an older neighbour as the benchmark
  and the full Eric ladder runs: strata harmonisation, age gap at $50 psf/year, MRT, mall,
  school, view.

The benchmark ladder reproduces Eric's published Pinery working to within $11 psf
($2,539 vs his $2,550) when fed Treasure at Tampines with a 7-year age gap.

### Picking a benchmark

Only needed for a **new launch with no transaction history**. For a resale, leave it blank — the
project's own prints are always the better comp.

A good benchmark is **older and established**, in the same district or one MRT stop away, with the
same bedroom count and plenty of resale prints. **Suggest benchmarks from the data** ranks the
candidates for you: same district, same bedroom type, filtered to 60%+ resale (the signal that a
project is established rather than still selling new units), sorted by transaction count. For a
D18 3-bedder it puts Treasure at Tampines first — the project Eric actually used.

### Age gap

**Age gap = your TOP year − the benchmark's TOP year.** Fill in both and it computes itself; type
a number to override. Eric adds **$50 psf per year** the benchmark is older, dropping to $40 once
the benchmark is past 20 years old. The hint line under the field shows the resulting dollar
figure before you run anything.

Note this is the gap **at your completion year**, not today — Pinery (TOP 2029) against Treasure
(TOP 2022) is a 7-year gap worth +$350 psf, even though Treasure is only 4 years old right now.

### Size band

The ± window around your size that a comp must fall inside. Keep it at 10–15% for a common
layout; widen to 25% or Any if the comps table comes back nearly empty. **Window** is how far back
to look — 12 months is freshest, 24–36 for a quiet project.

---

## Data

`ura_data.js` — 126,590 private residential transactions, 2021 onwards, from the URA Data
Service. Generated, not committed. Regenerate with either:

```bash
python fetch_ura_data.py
python .claude/skills/property-analysis/scripts/ura_live.py --refresh-transactions
```

Both need a free URA AccessKey from https://eservice.ura.gov.sg/maps/api/.

---

## The companion scripts

All live in `.claude/skills/property-analysis/scripts/`. The first three need **no API key**.

```bash
# comps, project vitals, transaction velocity
python .claude/skills/property-analysis/scripts/comps.py \
  --project "Grand Dunman" --size 1119 --price 2650000 --bedrooms 3 --table

# MRT walking distance + elite primaries within 1km (OneMap)
python .claude/skills/property-analysis/scripts/location.py --project "Grand Dunman" --table

# the HDB upgrader pool that buys this from you (data.gov.sg)
python .claude/skills/property-analysis/scripts/hdb.py --town GEYLANG --table

# median rentals, yield, and competing supply (URA API — needs a key)
python .claude/skills/property-analysis/scripts/ura_live.py \
  --service PMI_Resi_Rental_Median --project "Grand Dunman" --price 2650000 --table
```

---

## Model constants

Every adjustment and score weight is documented in
`.claude/skills/property-analysis/references/scoring.md`, and the rule set behind them in
`references/framework.md`. The app and the skill implement the same model — change the reference
and change both.

---

This is a framework-based valuation from historical transaction data. It is not financial advice
and not a professional valuation.
