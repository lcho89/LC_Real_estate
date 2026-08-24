#!/usr/bin/env python3
"""
fetch_ura_data.py
─────────────────
Fetches Singapore private residential property transaction data from the
URA Data Service API and saves it as ura_data.js for use with
index.html

Requirements:
    pip install requests

Usage:
    python fetch_ura_data.py
    python fetch_ura_data.py --key YOUR_KEY --token YOUR_TOKEN
    python fetch_ura_data.py --key YOUR_KEY --token YOUR_TOKEN --out ura_data.js

URA API registration (free):
    https://eservice.ura.gov.sg/maps/api/

Note: A new Token must be generated each day via:
    GET https://eservice.ura.gov.sg/uraDataService/insertNewToken/v1
    Headers: AccessKey: <your-key>
"""

import requests
import json
import sys
import argparse
from datetime import datetime

# ─────────────────────────────────────────────
#  Constants
# ─────────────────────────────────────────────

BASE_URL = "https://eservice.ura.gov.sg/uraDataService/invokeUraDS/v1"
SQM_TO_SQFT = 10.7639

PROPERTY_TYPES_INCLUDE = {"Condominium", "Apartment", "Executive Condominium"}

SALE_TYPE_MAP = {
    "1": "New Sale",
    "2": "Sub-sale",
    "3": "Resale",
}

BATCH_LABELS = {
    1: "Districts 01–07",
    2: "Districts 08–14",
    3: "Districts 15–21",
    4: "Districts 22+",
}

# ─────────────────────────────────────────────
#  Derivation helpers
# ─────────────────────────────────────────────

def area_to_bedroom(area_sqm: float) -> str:
    """Infer bedroom type from floor area (sqm). URA does not provide bedroom count."""
    sqft = area_sqm * SQM_TO_SQFT
    if sqft <= 430:
        return "Studio"
    elif sqft <= 650:
        return "1-Bedroom"
    elif sqft <= 970:
        return "2-Bedroom"
    elif sqft <= 1300:
        return "3-Bedroom"
    elif sqft <= 2000:
        return "4-Bedroom"
    elif sqft <= 2800:
        return "5-Bedroom"
    else:
        return "Penthouse"


def get_size_band(sqft: float) -> str:
    """Bucket floor area into display bands matching the dashboard filter."""
    if sqft <  500: return "< 500"
    if sqft <  600: return "500-600"
    if sqft <  700: return "600-700"
    if sqft <  800: return "700-800"
    if sqft <  900: return "800-900"
    if sqft < 1000: return "900-1,000"
    if sqft < 1200: return "1,000-1,200"
    if sqft < 1500: return "1,200-1,500"
    return "> 1,500"


def parse_tenure(tenure_str: str) -> tuple:
    """Returns (tenureType, tenureLabel) from raw URA tenure string.
    Preserves the full string (e.g. '99 years lease commencing from 2017')
    so the dashboard can extract the lease commencement year."""
    if not tenure_str:
        return "Unknown", "Unknown"
    s = tenure_str.strip()
    if s.lower() == "freehold":
        return "Freehold", "Freehold"
    low = s.lower()
    if "999" in low:
        return "Leasehold", s
    if "99" in low or "103" in low or "60" in low or "30" in low:
        return "Leasehold", s
    return "Leasehold", s


def parse_contract_date(date_str: str):
    """Parse 'MMYY' → (year, month). Returns (None, None) on failure."""
    if not date_str or len(date_str) != 4:
        return None, None
    try:
        mm = int(date_str[:2])
        yy = int(date_str[2:])
        if not (1 <= mm <= 12):
            return None, None
        year = 2000 + yy
        return year, mm
    except ValueError:
        return None, None


def format_project_name(raw: str) -> str:
    """Title-case a project name, preserving common abbreviations."""
    # Simple title case with a few exceptions
    words = raw.title().split()
    small = {"At", "Of", "In", "On", "By", "The", "And", "Or", "A"}
    result = []
    for i, w in enumerate(words):
        # Always capitalise first word; lowercase small words mid-name
        if i > 0 and w in small:
            result.append(w.lower())
        else:
            result.append(w)
    return " ".join(result)

# ─────────────────────────────────────────────
#  API fetch
# ─────────────────────────────────────────────

def fetch_batch(session: requests.Session, batch: int, headers: dict) -> list:
    """Fetch one batch from URA API. Returns list of processed transaction dicts."""
    url = f"{BASE_URL}?service=PMI_Resi_Transaction&batch={batch}"
    try:
        r = session.get(url, headers=headers, timeout=45)
        r.raise_for_status()
        data = r.json()
    except requests.exceptions.Timeout:
        print(f"    ⚠  Timeout on batch {batch}", file=sys.stderr)
        return []
    except requests.exceptions.HTTPError as e:
        print(f"    ⚠  HTTP {e.response.status_code} on batch {batch}", file=sys.stderr)
        return []
    except (json.JSONDecodeError, ValueError):
        print(f"    ⚠  Invalid JSON on batch {batch}", file=sys.stderr)
        return []

    if data.get("Status") != "Success":
        msg = data.get("Message", "Unknown error")
        print(f"    ⚠  API error (batch {batch}): {msg}", file=sys.stderr)
        return []

    records = []
    for project in data.get("Result", []):
        raw_name = project.get("project", "")
        if not raw_name:
            continue
        project_name  = format_project_name(raw_name)
        market_segment = project.get("marketSegment", "")
        # URA returns tenure per transaction; this project-level value is only a
        # fallback for the rare record that carries it on the project instead.
        project_tenure = project.get("tenure", "") or ""

        for tx in project.get("transaction", []):
            # Filter property types
            prop_type = tx.get("propertyType", "")
            if prop_type not in PROPERTY_TYPES_INCLUDE:
                continue

            # Parse numerics
            try:
                area_sqm = float(tx.get("area", 0) or 0)
                price    = float(tx.get("price", 0) or 0)
            except (ValueError, TypeError):
                continue
            if area_sqm <= 0 or price <= 0:
                continue

            area_sqft = round(area_sqm * SQM_TO_SQFT)
            psf       = round(price / area_sqft)

            # Date
            year, month = parse_contract_date(tx.get("contractDate", ""))
            if year is None:
                continue

            # District
            district_raw = tx.get("district", "00")
            district = f"D{district_raw.zfill(2)}"

            # Tenure lives on the transaction. Fall back to the project only when absent.
            raw_tenure = (tx.get("tenure", "") or "").strip() or project_tenure
            tenure_type, tenure_label = parse_tenure(raw_tenure)

            # Derived fields
            bedroom   = area_to_bedroom(area_sqm)
            sale_type = SALE_TYPE_MAP.get(tx.get("typeOfSale", ""), "Unknown")

            records.append({
                "project":          project_name,
                "district":         district,
                "tenureType":       tenure_type,
                "tenure":           tenure_label,
                "bedroomType":      bedroom,
                "sizeBand":         get_size_band(area_sqft),
                "size":             area_sqft,
                "psf":              psf,
                "transactionValue": round(price / 1000) * 1000,
                "year":             year,
                "month":            month,
                "marketSegment":    market_segment,
                "propertyType":     prop_type,
                "floorRange":       tx.get("floorRange", ""),
                "saleType":         sale_type,
            })

    return records

# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fetch URA residential transaction data for index.html"
    )
    parser.add_argument("--key",   help="URA Access Key")
    parser.add_argument("--token", help="URA Daily Token")
    parser.add_argument("--out",   default="ura_data.js", help="Output JS file (default: ura_data.js)")
    parser.add_argument("--batches", default="1,2,3,4", help="Comma-separated batch numbers to fetch (default: 1,2,3,4)")
    args = parser.parse_args()

    print()
    print("=" * 60)
    print("  URA Transaction Data Fetcher - index.html")
    print("=" * 60)
    print()

    # Get credentials
    access_key = args.key or input("  URA Access Key  : ").strip()
    token      = args.token or input("  Daily Token     : ").strip()
    print()

    if not access_key or not token:
        print("Error: Both Access Key and Token are required.")
        sys.exit(1)

    # URA sits behind a WAF that drops default tool user-agents (including
    # requests' own), so present a normal browser one.
    headers = {
        "AccessKey": access_key,
        "Token": token,
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    }
    batches = [int(b.strip()) for b in args.batches.split(",") if b.strip().isdigit()]

    # Fetch all batches
    session = requests.Session()
    all_records = []

    for batch_num in batches:
        label = BATCH_LABELS.get(batch_num, f"Batch {batch_num}")
        print(f"  Fetching batch {batch_num}/4  ({label}) … ", end="", flush=True)
        records = fetch_batch(session, batch_num, headers)
        all_records.extend(records)
        print(f"{len(records):,} records")

    print()

    if not all_records:
        print("  ✗ No records fetched. Please verify your Access Key and Token.")
        print("    Generate a fresh Token at:")
        print("    GET https://eservice.ura.gov.sg/uraDataService/insertNewToken/v1")
        print("    Headers: AccessKey: <your-key>")
        sys.exit(1)

    # Summary
    years     = sorted({r["year"] for r in all_records})
    districts = sorted({r["district"] for r in all_records})
    projects  = sorted({r["project"] for r in all_records})

    print(f"  Total records : {len(all_records):,}")
    print(f"  Years         : {min(years)}–{max(years)}")
    print(f"  Districts     : {', '.join(districts[:10])}{'…' if len(districts)>10 else ''}")
    print(f"  Projects      : {len(projects):,} unique")
    print()

    # Save as ura_data.js — compact columnar format to keep file small
    output_path  = args.out
    fetched_at   = datetime.now().strftime("%Y-%m-%d")

    # Build compact format: {cols:[...], rows:[[...], ...]}
    cols = ["project","district","tenureType","tenure","bedroomType","sizeBand",
            "size","psf","transactionValue","year","month",
            "marketSegment","propertyType","floorRange","saleType"]
    rows = [[r.get(c,"") for c in cols] for r in all_records]
    compact = {"cols": cols, "rows": rows, "fetchedAt": fetched_at}

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"// URA Real Data — {fetched_at} — {len(all_records)} records\n")
        f.write("window.URA_DATA=")
        json.dump(compact, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")

    print(f"  ✓ Saved {len(all_records):,} records → {output_path}")
    print()
    print("  Next step:")
    print(f"   Place '{output_path}' in the same folder as index.html")
    print("   Then open (or refresh) index.html — it will load automatically.")
    print()
    print("  Refresh cadence:")
    print("   URA publishes on a monthly cycle — re-run this on the 1st of each month.")
    print("   The dashboard flags the data as stale once it is a month old.")
    print()


if __name__ == "__main__":
    main()
