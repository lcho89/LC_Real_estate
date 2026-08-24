#!/usr/bin/env python3
"""
hdb.py — the MOP upgrader pool, measured from live data.gov.sg HDB resale records.

Eric's second question is "who buys this from you in 4-5 years?". His answer is the pool of
HDB upgraders next door: owners who just crossed MOP, made 2-2.5x on their flat, and now want
a condo in the same estate. This script measures that pool for real.

No API key required — data.gov.sg's datastore is open.

Usage
-----
    python hdb.py --town GEYLANG --table
    python hdb.py --town "BUKIT MERAH" --street "DAKOTA" --months 24
    python hdb.py --town TAMPINES --flat-type "5 ROOM" --table
    python hdb.py --list-towns

What it reports
---------------
  * resale volume and median price by flat type
  * million-dollar flats: count, share, trend
  * the fresh-MOP wave: flats with 90+ years of lease left (i.e. recently MOP'd BTOs)
  * price momentum over the requested window
"""

import argparse
import json
import statistics
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date

RESOURCE_ID = "d_8b84c4ee58e3cfc0ece0d773c8ca6abc"   # Resale flat prices, Jan-2017 onwards
API = "https://data.gov.sg/api/action/datastore_search"

TOWNS = [
    "ANG MO KIO", "BEDOK", "BISHAN", "BUKIT BATOK", "BUKIT MERAH", "BUKIT PANJANG",
    "BUKIT TIMAH", "CENTRAL AREA", "CHOA CHU KANG", "CLEMENTI", "GEYLANG", "HOUGANG",
    "JURONG EAST", "JURONG WEST", "KALLANG/WHAMPOA", "MARINE PARADE", "PASIR RIS",
    "PUNGGOL", "QUEENSTOWN", "SEMBAWANG", "SENGKANG", "SERANGOON", "TAMPINES",
    "TOA PAYOH", "WOODLANDS", "YISHUN",
]

# Estates Eric names as million-dollar-flat engines.
UPGRADER_ENGINES = {"BISHAN", "TOA PAYOH", "QUEENSTOWN", "KALLANG/WHAMPOA",
                    "CLEMENTI", "BUKIT MERAH", "CENTRAL AREA", "MARINE PARADE"}


def fetch(params):
    url = f"{API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "property-analysis/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def cutoff_month(months):
    today = date.today()
    total = today.year * 12 + (today.month - 1) - months
    return f"{total // 12}-{(total % 12) + 1:02d}"


def collect(town, months, flat_type=None, street=None, page_size=1000, max_pages=40):
    """Newest-first paging until we fall out of the requested window."""
    floor = cutoff_month(months)
    filters = {"town": town.upper()}
    if flat_type:
        filters["flat_type"] = flat_type.upper()

    records, offset = [], 0
    for _ in range(max_pages):
        params = {
            "resource_id": RESOURCE_ID,
            "limit": page_size,
            "offset": offset,
            "filters": json.dumps(filters),
            "sort": "_id desc",
        }
        data = fetch(params)
        batch = data.get("result", {}).get("records", [])
        if not batch:
            break
        stop = False
        for r in batch:
            if r["month"] < floor:
                stop = True
                continue
            if street and street.upper() not in r["street_name"].upper():
                continue
            records.append(r)
        offset += page_size
        if stop or len(batch) < page_size:
            break
    return records, floor


def lease_years(remaining):
    """'65 years 05 months' -> 65.4"""
    try:
        parts = remaining.split()
        y = int(parts[0])
        m = int(parts[2]) if len(parts) > 3 else 0
        return y + m / 12
    except (ValueError, IndexError):
        return None


def analyse(args):
    if args.list_towns:
        return {"towns": TOWNS}
    if not args.town:
        return {"error": "Pass --town (see --list-towns)."}

    records, floor = collect(args.town, args.months, args.flat_type, args.street)
    if not records:
        return {"error": f"No HDB resale records for {args.town} since {floor}.",
                "hint": "Check the town spelling with --list-towns."}

    prices = [float(r["resale_price"]) for r in records]
    by_type = defaultdict(list)
    by_month = defaultdict(list)
    fresh_mop = []
    million = []

    for r in records:
        p = float(r["resale_price"])
        by_type[r["flat_type"]].append(p)
        by_month[r["month"]].append(p)
        if p >= 1_000_000:
            million.append(r)
        yrs = lease_years(r.get("remaining_lease", ""))
        if yrs is not None and yrs >= 90:
            fresh_mop.append(r)

    months_sorted = sorted(by_month)
    early = months_sorted[: max(1, len(months_sorted) // 3)]
    late = months_sorted[-max(1, len(months_sorted) // 3):]
    early_med = statistics.median([p for m in early for p in by_month[m]])
    late_med = statistics.median([p for m in late for p in by_month[m]])
    momentum = round((late_med / early_med - 1) * 100, 1) if early_med else None

    fresh_prices = [float(r["resale_price"]) for r in fresh_mop]

    out = {
        "town": args.town.upper(),
        "street_filter": args.street,
        "window_months": args.months,
        "from_month": floor,
        "transactions": len(records),
        "median_price": round(statistics.median(prices)),
        "by_flat_type": {
            t: {"n": len(v), "median": round(statistics.median(v)),
                "max": round(max(v))}
            for t, v in sorted(by_type.items(), key=lambda kv: -len(kv[1]))
        },
        "million_dollar_flats": {
            "count": len(million),
            "share_pct": round(len(million) / len(records) * 100, 1),
            "top": sorted(
                ({"month": r["month"], "block": r["block"], "street": r["street_name"],
                  "flat_type": r["flat_type"], "price": round(float(r["resale_price"])),
                  "storey": r["storey_range"]} for r in million),
                key=lambda x: -x["price"])[:8],
        },
        "fresh_mop_wave": {
            "definition": "resale flats with 90+ years of lease remaining = recently MOP'd BTOs",
            "count": len(fresh_mop),
            "share_pct": round(len(fresh_mop) / len(records) * 100, 1),
            "median_price": round(statistics.median(fresh_prices)) if fresh_prices else None,
            "streets": [s for s, _ in Counter(r["street_name"] for r in fresh_mop).most_common(6)],
        },
        "price_momentum_pct": momentum,
        "is_named_upgrader_engine": args.town.upper() in UPGRADER_ENGINES,
        "source": "data.gov.sg resource d_8b84c4ee58e3cfc0ece0d773c8ca6abc (open, no key)",
    }

    pool = out["fresh_mop_wave"]["count"]
    mdf = out["million_dollar_flats"]["count"]
    out["verdict"] = (
        f"Strong upgrader pool: {pool} freshly-MOP'd flats sold in {args.months} months, "
        f"{mdf} of them million-dollar prints. This is a concrete answer to 'who buys from you'."
        if pool >= 100 and mdf >= 5 else
        f"Workable upgrader pool: {pool} freshly-MOP'd resales, {mdf} million-dollar flats."
        if pool >= 30 else
        f"Thin upgrader pool: only {pool} freshly-MOP'd resales in {args.months} months. "
        "The exit depends on someone other than HDB upgraders — name them or walk."
    )
    return out


def render(res):
    if "towns" in res:
        print("\n".join(res["towns"]))
        return
    if "error" in res:
        print(res["error"])
        if res.get("hint"):
            print(res["hint"])
        return

    print(f"\nHDB POOL  {res['town']}"
          + (f" / {res['street_filter']}" if res["street_filter"] else ""))
    print(f"          {res['transactions']} resales since {res['from_month']}, "
          f"median ${res['median_price']:,}")
    if res["price_momentum_pct"] is not None:
        print(f"          price momentum over the window: {res['price_momentum_pct']:+.1f}%")
    if res["is_named_upgrader_engine"]:
        print("          this is one of the estates Eric names as a million-dollar-flat engine")

    print("\nBY FLAT TYPE")
    for t, v in res["by_flat_type"].items():
        print(f"  {t:<12} n={v['n']:<5} median ${v['median']:>9,}   max ${v['max']:>9,}")

    m = res["million_dollar_flats"]
    print(f"\nMILLION-DOLLAR FLATS  {m['count']} ({m['share_pct']}% of resales)")
    for f in m["top"][:5]:
        print(f"  {f['month']}  blk {f['block']:<5} {f['street'][:24]:<24} "
              f"{f['flat_type']:<8} ${f['price']:>9,}  {f['storey']}")

    w = res["fresh_mop_wave"]
    print(f"\nFRESH MOP WAVE  {w['count']} ({w['share_pct']}%)  "
          f"median ${w['median_price']:,}" if w["median_price"] else
          f"\nFRESH MOP WAVE  {w['count']}")
    if w["streets"]:
        print("  hot streets: " + ", ".join(w["streets"]))

    print(f"\n{res['verdict']}\n")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--town", help="HDB town, e.g. GEYLANG")
    p.add_argument("--street", help="Filter to street names containing this substring")
    p.add_argument("--flat-type", help="e.g. '4 ROOM', '5 ROOM'")
    p.add_argument("--months", type=int, default=24, help="Lookback window (default 24)")
    p.add_argument("--list-towns", action="store_true")
    p.add_argument("--table", action="store_true", help="Human-readable output")
    args = p.parse_args()

    res = analyse(args)
    if args.table:
        render(res)
    else:
        json.dump(res, sys.stdout, indent=2)
        print()


if __name__ == "__main__":
    main()
