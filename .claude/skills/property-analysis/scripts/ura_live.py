#!/usr/bin/env python3
"""
ura_live.py — live queries against the URA Data Service API.

Covers the three things the local ura_data.js snapshot cannot give you:
  * median rentals for a project      -> gross yield, and the holding-cost side of the
                                         opportunity-cost model
  * the supply pipeline               -> the "9 competing plots in Lentor" oversupply check
  * a fresh transaction pull          -> when the local snapshot has gone stale

Credentials
-----------
Register free at https://eservice.ura.gov.sg/maps/api/ for an AccessKey.
A Token must be minted daily from that key. Supply them by either:

    set URA_ACCESS_KEY=...        (and optionally URA_TOKEN=...)
    python ura_live.py --key <accesskey> --token <token>

With only the key, this script mints a token for you and prints it.

Usage
-----
    python ura_live.py --token-only
    python ura_live.py --service PMI_Resi_Rental_Median --project "Grand Dunman" --table
    python ura_live.py --service PMI_Resi_Rental_Median --project "Grand Dunman" --price 2650000 --size 1119
    python ura_live.py --service PMI_Resi_Pipeline --district 15 --table
    python ura_live.py --refresh-transactions
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import urllib.parse
import urllib.request

BASE = "https://eservice.ura.gov.sg/uraDataService"
TOKEN_URL = f"{BASE}/insertNewToken/v1"
DS_URL = f"{BASE}/invokeUraDS/v1"

SERVICES = {
    "PMI_Resi_Transaction": "Private residential transactions (needs batch=1..4)",
    "PMI_Resi_Rental_Median": "Median rentals of private non-landed homes, past 3 years",
    "PMI_Resi_Rental_Contract": "Individual rental contracts, past 3 years",
    "PMI_Resi_Pipeline": "Project supply pipeline, latest quarter",
    "PMI_Resi_Private_Median": "Median price of uncompleted private residential units",
}


def call(url, key, token=None):
    headers = {"AccessKey": key, "User-Agent": "property-analysis/1.0"}
    if token:
        headers["Token"] = token
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def mint_token(key):
    data = call(TOKEN_URL, key)
    if data.get("Status") != "Success":
        sys.exit(f"Token request failed: {data.get('Message', data)}")
    return data["Result"]


def credentials(args):
    key = args.key or os.environ.get("URA_ACCESS_KEY")
    if not key:
        sys.exit(
            "No URA AccessKey. Register free at https://eservice.ura.gov.sg/maps/api/ then:\n"
            "  set URA_ACCESS_KEY=your-key\n"
            "or pass --key."
        )
    token = args.token or os.environ.get("URA_TOKEN")
    if not token:
        token = mint_token(key)
        print(f"[minted a fresh URA token: {token}]", file=sys.stderr)
    return key, token


# ─────────────────────────────────────────────────────────────
#  Service handlers
# ─────────────────────────────────────────────────────────────

def rental_median(result, args):
    """Filter the median-rental feed to one project and derive yield."""
    want = (args.project or "").strip().upper()
    rows = []
    for entry in result:
        name = (entry.get("project") or "").upper()
        if want and want not in name:
            continue
        street = entry.get("street", "")
        for r in entry.get("rentalMedian", []):
            median = r.get("median")
            if median in (None, "", "-"):
                continue
            rows.append({
                "project": entry.get("project"),
                "street": street,
                "district": entry.get("district"),
                "quarter": r.get("refPeriod"),
                "bedrooms": r.get("bedrooms"),
                "median_rent": float(median),
                "psm25": r.get("psm25"), "psm75": r.get("psm75"),
            })

    rows.sort(key=lambda x: (x["quarter"] or "", x["bedrooms"] or ""), reverse=True)
    out = {"service": "PMI_Resi_Rental_Median", "project_filter": args.project,
           "rows": rows[:60], "n": len(rows)}

    if rows:
        latest_q = rows[0]["quarter"]
        latest = [r for r in rows if r["quarter"] == latest_q]
        out["latest_quarter"] = latest_q
        out["latest_by_bedroom"] = {
            str(r["bedrooms"]): round(r["median_rent"]) for r in latest
        }
        rents = [r["median_rent"] for r in latest]
        out["median_rent_latest"] = round(statistics.median(rents))

        if args.price:
            bed = str(args.bedrooms) if args.bedrooms else None
            rent = (out["latest_by_bedroom"].get(bed)
                    if bed and bed in out["latest_by_bedroom"]
                    else out["median_rent_latest"])
            gross = rent * 12 / args.price * 100
            out["yield_analysis"] = {
                "monthly_rent_used": rent,
                "gross_yield_pct": round(gross, 2),
                "net_yield_pct_est": round(gross * 0.75, 2),
                "annual_net_rent_est": round(rent * 12 * 0.75),
                "four_year_net_rent_est": round(rent * 12 * 0.75 * 4),
                "note": ("Net assumes 25% goes to maintenance, property tax, agent fees and "
                         "vacancy. The four-year figure is the resale side of the "
                         "opportunity-cost comparison; a new launch earns nothing over the "
                         "same window and pays rent instead."),
            }
    return out


def pipeline(result, args):
    """Supply in the pipeline — the oversupply / competing-launch check."""
    rows = []
    for e in result:
        d = str(e.get("district") or "").zfill(2)
        if args.district and d != str(args.district).lstrip("D").zfill(2):
            continue
        rows.append({
            "project": e.get("project"),
            "street": e.get("street"),
            "district": f"D{d}",
            "developer": e.get("developer"),
            "type": e.get("type"),
            "total_units": e.get("totalUnits"),
            "units_launched": e.get("unitsLaunchedToDate"),
            "units_sold": e.get("unitsSoldToDate"),
            "expected_top": e.get("expectedTOPDate"),
            "market_segment": e.get("marketSegment"),
        })

    def as_int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    total = sum(as_int(r["total_units"]) for r in rows)
    unsold = sum(as_int(r["total_units"]) - as_int(r["units_sold"]) for r in rows)
    rows.sort(key=lambda r: -as_int(r["total_units"]))
    return {
        "service": "PMI_Resi_Pipeline",
        "district_filter": args.district,
        "projects": len(rows),
        "total_units_in_pipeline": total,
        "unsold_units": unsold,
        "absorption_pct": round((total - unsold) / total * 100, 1) if total else None,
        "rows": rows[:40],
        "oversupply_verdict": (
            "heavy competing supply — Eric's Lentor problem: every neighbouring launch "
            "competes with your exit" if len(rows) >= 6 else
            "moderate competing supply" if len(rows) >= 3 else
            "little competing supply in the district"
        ),
    }


def generic(result, args):
    return {"service": args.service, "n": len(result), "rows": result[:40]}


# ─────────────────────────────────────────────────────────────

def refresh_transactions(args):
    """Delegate to the repo's existing fetch_ura_data.py."""
    here = os.path.abspath(os.path.dirname(__file__))
    root = os.path.abspath(os.path.join(here, "..", "..", "..", ".."))
    script = os.path.join(root, "fetch_ura_data.py")
    if not os.path.exists(script):
        sys.exit(f"fetch_ura_data.py not found at {script}")
    key, token = credentials(args)
    out = args.out or os.path.join(root, "property-analyzer", "ura_data.js")
    cmd = [sys.executable, "-X", "utf8", script, "--key", key, "--token", token, "--out", out]
    print(f"Refreshing transactions -> {out}", file=sys.stderr)
    return subprocess.call(cmd, cwd=root)


def render(res):
    svc = res.get("service")
    if svc == "PMI_Resi_Rental_Median":
        print(f"\nRENTALS  {res.get('project_filter') or 'all projects'}  "
              f"({res['n']} median rows)")
        if res.get("latest_quarter"):
            print(f"         latest quarter {res['latest_quarter']}")
            for bed, rent in sorted(res["latest_by_bedroom"].items()):
                print(f"           {bed} bedroom: ${rent:,}/month")
        y = res.get("yield_analysis")
        if y:
            print(f"\nYIELD    rent used ${y['monthly_rent_used']:,}/month")
            print(f"         gross {y['gross_yield_pct']}%   net (est) {y['net_yield_pct_est']}%")
            print(f"         4-year net rental income est ${y['four_year_net_rent_est']:,}")
            print(f"         {y['note']}")
        print()
        return

    if svc == "PMI_Resi_Pipeline":
        print(f"\nPIPELINE  district {res.get('district_filter') or 'all'}: "
              f"{res['projects']} projects, {res['total_units_in_pipeline']:,} units, "
              f"{res['unsold_units']:,} unsold ({res['absorption_pct']}% absorbed)")
        for r in res["rows"][:15]:
            print(f"  {str(r['project'])[:30]:<30} {r['district']:<5} "
                  f"{str(r['total_units']):>5} units  sold {str(r['units_sold']):>5}  "
                  f"TOP {r['expected_top']}")
        print(f"\n{res['oversupply_verdict']}\n")
        return

    json.dump(res, sys.stdout, indent=2)
    print()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--service", choices=list(SERVICES), help="URA data service to call")
    p.add_argument("--batch", type=int, help="Batch 1-4, required for PMI_Resi_Transaction")
    p.add_argument("--project", help="Filter to a project name (substring, case-insensitive)")
    p.add_argument("--district", help="Filter to a district, e.g. 15 or D15")
    p.add_argument("--price", type=float, help="Asking price, for the yield calculation")
    p.add_argument("--size", type=float, help="Size in sqft")
    p.add_argument("--bedrooms", type=int, help="Bedroom count, for the yield calculation")
    p.add_argument("--key", help="URA AccessKey (or set URA_ACCESS_KEY)")
    p.add_argument("--token", help="URA daily Token (or set URA_TOKEN)")
    p.add_argument("--token-only", action="store_true", help="Mint and print a token, then exit")
    p.add_argument("--refresh-transactions", action="store_true",
                   help="Re-download the full transaction dataset via fetch_ura_data.py")
    p.add_argument("--out", help="Output path for --refresh-transactions")
    p.add_argument("--list-services", action="store_true")
    p.add_argument("--table", action="store_true", help="Human-readable output")
    args = p.parse_args()

    if args.list_services:
        for k, v in SERVICES.items():
            print(f"{k:<26} {v}")
        return

    if args.token_only:
        key = args.key or os.environ.get("URA_ACCESS_KEY")
        if not key:
            sys.exit("Pass --key or set URA_ACCESS_KEY.")
        print(mint_token(key))
        return

    if args.refresh_transactions:
        sys.exit(refresh_transactions(args))

    if not args.service:
        sys.exit("Pass --service (see --list-services), --token-only, or --refresh-transactions.")

    key, token = credentials(args)
    params = {"service": args.service}
    if args.service == "PMI_Resi_Transaction":
        params["batch"] = args.batch or 1
    url = f"{DS_URL}?{urllib.parse.urlencode(params)}"

    data = call(url, key, token)
    if data.get("Status") != "Success":
        sys.exit(f"URA API error: {data.get('Message', data)}")
    result = data.get("Result", [])

    handler = {"PMI_Resi_Rental_Median": rental_median,
               "PMI_Resi_Pipeline": pipeline}.get(args.service, generic)
    res = handler(result, args)

    if args.table:
        render(res)
    else:
        json.dump(res, sys.stdout, indent=2)
        print()


if __name__ == "__main__":
    main()
