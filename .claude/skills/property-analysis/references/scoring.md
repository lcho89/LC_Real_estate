# Scoring & Fair-Value Model

The deterministic implementation of the framework. The browser app
(`property-analyzer/index.html`) implements exactly this model — keep the two in sync.

---

## Part A — Fair value ladder

Start from a comp baseline PSF, then apply adjustments in order. Show every line.

```
  comp baseline PSF                     (median PSF of the chosen comp tier)
+ strata harmonisation                  +5% of baseline, clamped to +$100 … +$200 psf
                                        (only when subject is a post-2023 launch and comp is not)
+ age gap                               ($/psf per year) x (comp age - subject age)
+ MRT premium                           see table
+ mall premium                          see table
+ school premium                        see table
+ view premium                          see table
+ distance-to-town                      -$100 psf per extra MRT stop from town vs the comp
+ floor premium                         +0.4% of baseline per storey above the comp's floor band
= FAIR PSF
x subject size (sqft)                   = FAIR QUANTUM
```

### Constants

| Adjustment | Value | Source |
|---|---|---|
| Age gap, comps under 20 yrs old | **+$50 psf per year** the comp is older | Pinery, Rivelle, Tengah, Dunearn workings |
| Age gap, comps 20 yrs+ | **+$40 psf per year** (conservative) | Costa Del Sol / Vela Bay working |
| Strata harmonisation | **+5% of baseline**, clamp $100–$200 psf | Pinery (+$91), Vela Bay (+$100), "~$200 psf" rule |
| MRT — integrated / direct link | **+$100 psf** | Pinery, Tengah |
| MRT — subject materially closer (<300 m vs comp 500 m+) | **+$50 psf** | Tengah ("stick to station vs 500 m walk") |
| MRT — subject materially further | **−$50 to −$100 psf** | inverse |
| Mall — proper integrated mall (≥250k sqft) | **+$100 psf** | Pinery baseline premium |
| Mall — "pirated mall" (<250k sqft) | **+$50 psf** | Pinery adjustment downward |
| Elite primary within 1 km (whole project) | **+$100 psf** | Rivelle "MRT/mall/school premium $150" split |
| Elite primary — only some stacks | **+$50 psf** | Lentor Gardens |
| Sea / permanently unblocked view | **+$300 psf** | Costa Del Sol $3,100 vs $2,800 |
| One MRT stop closer to town | **+$100 psf** | Seaside vs Vela Bay |
| Floor | **+0.4% of baseline per storey** | standard market height premium |

### Worked example — Pinery Residences (reproduce this exactly)

```
Treasure at Tampines resale baseline, 3 yrs old        $1,909 psf
+ harmonisation (5%)                                     +$91
+ age gap, 7 years x $50                                +$350
+ MRT proximity premium                                 +$100
+ mixed-development mall premium (pirated, halved)      +$100
= fair price                                          $2,550 psf
```

### Comp tier priority

1. **Same project**, same bedroom type, ±15% size, last 12–18 months. Use when n ≥ 3.
2. **Same district + bedroom type**, ±15% size, last 12 months. Use when n ≥ 5.
3. **Same market segment + bedroom type**, last 12 months. Fallback only.
4. **Named benchmark project** the user or Eric specifies (the Treasure/Costa Del Sol pattern).

Use the **median**, not the mean — a few penthouse or fire-sale prints wreck a mean.
Always report `n` and the date range. If tier 1 has n < 3, that thin liquidity is itself an
exit-strategy penalty.

### Verdict bands

`gap = (fair PSF − asking PSF) / fair PSF`

| Gap | Verdict |
|---|---|
| ≥ +8% | **UNDERVALUED** — Eric's "undervalue gem" territory |
| +2% to +8% | **GOOD ENTRY** |
| −2% to +2% | **FAIRLY PRICED** |
| −2% to −10% | **RICH** — negotiate or walk |
| ≤ −10% | **OVERVALUED** — no room left for capital appreciation |

---

## Part B — The three scores

Each score starts at **5.0**, is adjusted, then clamped to **1–10**.
**Final score = (Location + Pricing + Exit) / 3**, rounded to 1 decimal.

### B1. Location

| Factor | Adjustment |
|---|---|
| MRT ≤ 100 m (integrated / direct link) | +2.5 |
| MRT 101–300 m | +2.0 |
| MRT 301–500 m | +1.5 |
| MRT 501–700 m | +0.5 |
| MRT 701–1,000 m | −1.0 |
| MRT > 1,000 m | −2.5 |
| Two or more elite primaries within 1 km | +1.5 |
| One elite primary within 1 km (whole project) | +1.0 |
| Elite primary, edge stacks only | +0.5 |
| Integrated mall ≥250k sqft | +1.0 |
| Integrated mall <250k sqft ("pirated") | +0.5 |
| Major mall within 500 m | +0.75 |
| Mature, high-density estate with real foot traffic | +0.5 |
| "Introvert" / low-density area (Panjang-type, West Coast, far OCR) | −1.5 |
| Expressway noise or industrial / wholesale surroundings | −0.5 |
| Sea or permanently unblocked view | +0.5 |

### B2. Pricing (entry price is king)

| Factor | Adjustment |
|---|---|
| Fair-value gap | +0.5 per +2% undervalued, −0.5 per 2% overvalued, capped at ±4.0 |
| OCR and asking PSF > $2,500 | −1.5 ("disgusting") |
| OCR and asking PSF ≤ $2,200 | +0.5 |
| Asking PSF below the 25th percentile of district + bedroom comps | +0.5 |
| Asking PSF above the 75th percentile of district + bedroom comps | −0.5 |
| Quantum in the $1.8M–$2.0M sweet spot for a 3/4-bedder | +0.5 |
| Developer land cost known and low for its era (below segment median psf ppr) | +0.5 |
| Land bought at a cycle peak (2018 en bloc wave, record-setting tender) | −1.0 |

### B3. Exit strategy (the one that decides it)

| Factor | Adjustment |
|---|---|
| Project ≥ 1,000 units | +2.0 |
| 400–999 units | +1.0 |
| 200–399 units | −1.0 |
| 100–199 units | −2.0 |
| < 100 units | −3.0 |
| 24-month transaction count in the project ≥ 40 | +1.0 |
| 15–39 | +0.5 |
| 5–14 | 0 |
| 1–4 | −1.0 |
| 0 | −2.0 (the Lilium problem) |
| 3-bedroom or larger | +1.0 |
| 2-bed 2-bath | 0 |
| 2-bed 1-bath | −2.0 (veto) |
| 1-bedroom / studio | −1.5 |
| Executive Condominium | +2.0 |
| Segment OCR or RCR | +0.5 |
| Segment CCR | −1.5 |
| Freehold landed | +1.0 |
| 99-year leasehold landed | −3.0 (veto) |
| Remaining lease < 70 years | −2.0 |
| Freehold boutique (<200 units) with mostly small units | −0.5 |
| Nearby HDB blocks reaching MOP in the next 1–3 years | +1.0 |
| Project 3-yr PSF CAGR beats its district | +0.5 |
| Project 3-yr PSF CAGR trails its district | −0.5 |
| Heavy competing supply in the same enclave (≥4 launches) | −1.0 |
| Neighbouring projects with a documented loss history | −1.0 |

### Rating bands

| Final | Read |
|---|---|
| 8.0–10 | Buy — Eric's "you cannot lose money" tier |
| 7.0–7.9 | Solid, worth shortlisting |
| 6.0–6.9 | Marginal; only with a price concession |
| 5.0–5.9 | Weak — the exit is the problem |
| < 5.0 | Avoid |

---

## Part C — Opportunity-cost model

Always show the resale alternative against a new launch:

```
New launch:   gross gain over hold period − (months of rent while waiting x monthly rent)
Resale:       gross gain over hold period + (net rental income received)
```

Defaults when the user gives no figures: 3 years construction wait, rent $4,500/month
(OCR 3-bed) or $6,000/month (city fringe 3-bed), net rental yield after costs ≈ 2.5%.
Live median rentals for the specific project can be pulled with
`scripts/ura_live.py --service PMI_Resi_Rental_Median`.
