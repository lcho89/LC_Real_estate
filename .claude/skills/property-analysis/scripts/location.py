#!/usr/bin/env python3
"""
location.py — OneMap lookups for the location half of the framework.

Answers the two questions Eric refuses to compromise on:
  1. How far is the nearest MRT station, really?
  2. Which elite primary schools fall inside the 1 km radius?

Usage
-----
    python location.py --project "Grand Dunman"
    python location.py --project "Lentor Mansion" --table
    python location.py --address "2 Dunman Road" --radius 1200
    python location.py --refresh            # rebuild the MRT/school coordinate cache

Notes
-----
* OneMap's search endpoint returns results without a token (it prints an auth warning
  alongside the data). Station and school coordinates are cached locally after the first run.
* Straight-line distance is converted to an estimated walk with a 1.25x detour factor.
  Set ONEMAP_TOKEN to get true walking-route distances from OneMap's routing service.
  Get a token at https://www.onemap.gov.sg/apidocs/ (free account).
"""

import argparse
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request

SEARCH_URL = "https://www.onemap.gov.sg/api/common/elastic/search"
ROUTE_URL = "https://www.onemap.gov.sg/api/public/routingsvc/route"
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "onemap_cache.json")

WALK_FACTOR = 1.25          # straight line -> realistic walking path
WALK_SPEED_M_PER_MIN = 80   # ~4.8 km/h

# The schools that actually move prices in Eric's framework.
ELITE_PRIMARIES = [
    "NANYANG PRIMARY SCHOOL",
    "HENRY PARK PRIMARY SCHOOL",
    "CHIJ ST NICHOLAS GIRLS SCHOOL",
    "RAFFLES GIRLS PRIMARY SCHOOL",
    "AI TONG SCHOOL",
    "KONG HWA SCHOOL",
    "RULANG PRIMARY SCHOOL",
    "ANGLO-CHINESE SCHOOL PRIMARY",
    "TAO NAN SCHOOL",
    "CATHOLIC HIGH SCHOOL",
    "NAN HUA PRIMARY SCHOOL",
    "PEI HWA PRESBYTERIAN PRIMARY SCHOOL",
    "TEMASEK PRIMARY SCHOOL",
    "ST HILDA'S PRIMARY SCHOOL",
    "METHODIST GIRLS SCHOOL PRIMARY",
    "SINGAPORE CHINESE GIRLS SCHOOL",
    "ROSYTH SCHOOL",
    "RIVER VALLEY PRIMARY SCHOOL",
]


# ─────────────────────────────────────────────────────────────
#  HTTP
# ─────────────────────────────────────────────────────────────

def get_json(url, headers=None, retries=3):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "property-analysis/1.0"})
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:      # network hiccups are common against OneMap
            last = exc
            time.sleep(1 + attempt)
    raise RuntimeError(f"OneMap request failed after {retries} tries: {url}\n{last}")


def search(term, page=1):
    q = urllib.parse.urlencode({
        "searchVal": term, "returnGeom": "Y", "getAddrDetails": "Y", "pageNum": page,
    })
    return get_json(f"{SEARCH_URL}?{q}")


def geocode(term):
    """First usable hit for a free-text place name."""
    data = search(term)
    for r in data.get("results", []):
        if r.get("LATITUDE") and r.get("LONGITUDE"):
            return {
                "name": r.get("SEARCHVAL"),
                "address": r.get("ADDRESS"),
                "postal": r.get("POSTAL"),
                "lat": float(r["LATITUDE"]),
                "lng": float(r["LONGITUDE"]),
                "alternatives": [x.get("SEARCHVAL") for x in data.get("results", [])[1:5]],
            }
    return None


# ─────────────────────────────────────────────────────────────
#  Geometry
# ─────────────────────────────────────────────────────────────

def haversine_m(a_lat, a_lng, b_lat, b_lng):
    R = 6371000.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = p2 - p1
    dl = math.radians(b_lng - a_lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def walking_route_m(token, a, b):
    """True walking distance via OneMap routing. Returns None when unavailable."""
    if not token:
        return None
    q = urllib.parse.urlencode({
        "start": f"{a[0]},{a[1]}", "end": f"{b[0]},{b[1]}",
        "routeType": "walk",
    })
    try:
        data = get_json(f"{ROUTE_URL}?{q}", headers={"Authorization": token}, retries=1)
    except Exception:
        return None
    summ = (data.get("route_summary") or {})
    return round(summ.get("total_distance")) if summ.get("total_distance") else None


# ─────────────────────────────────────────────────────────────
#  Cache of station / school coordinates
# ─────────────────────────────────────────────────────────────

def load_cache():
    path = os.path.abspath(CACHE)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def save_cache(cache):
    path = os.path.abspath(CACHE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=1)


def collect_stations(term):
    """Page through OneMap for every station entry, keeping one point per station code."""
    first = search(term, 1)
    pages = int(first.get("totalNumPages", 1))
    seen = {}

    def absorb(results):
        for r in results:
            name = (r.get("SEARCHVAL") or "").upper()
            if "STATION" not in name or "EXIT" in name:
                continue
            if not r.get("LATITUDE"):
                continue
            # "BAYSHORE MRT STATION (TE29)" -> key on the code so exits/duplicates collapse
            code = name.split("(")[-1].rstrip(")") if "(" in name else name
            entry = seen.setdefault(code, {
                "station": name.split("(")[0].strip(),
                "codes": set(),
                "lat": float(r["LATITUDE"]),
                "lng": float(r["LONGITUDE"]),
            })
            entry["codes"].add(code)

    absorb(first.get("results", []))
    for p in range(2, pages + 1):
        absorb(search(term, p).get("results", []))
        time.sleep(0.12)
    return seen


def build_cache(verbose=True):
    cache = {"stations": [], "schools": []}
    merged = {}
    for term in ("MRT STATION", "LRT STATION"):
        if verbose:
            print(f"  fetching {term} ...", file=sys.stderr)
        merged.update(collect_stations(term))

    # One node per station name — OneMap returns a record per entrance, and interchanges
    # carry several line codes. Collapse to a centroid so a station is counted once.
    by_name = {}
    for e in merged.values():
        node = by_name.setdefault(e["station"], {"station": e["station"], "codes": set(),
                                                 "lats": [], "lngs": []})
        node["codes"] |= e["codes"]
        node["lats"].append(e["lat"])
        node["lngs"].append(e["lng"])
    cache["stations"] = [
        {
            "station": v["station"],
            # keep real line codes (CC8, TE29, NS1) and drop the fallback full-name keys
            "codes": sorted(c for c in v["codes"] if len(c) <= 6 and any(ch.isdigit() for ch in c)),
            "lat": sum(v["lats"]) / len(v["lats"]),
            "lng": sum(v["lngs"]) / len(v["lngs"]),
        }
        for v in by_name.values()
    ]

    if verbose:
        print(f"  {len(cache['stations'])} stations cached", file=sys.stderr)

    for name in ELITE_PRIMARIES:
        hit = geocode(name)
        if hit:
            cache["schools"].append({"school": name, "matched": hit["name"],
                                     "lat": hit["lat"], "lng": hit["lng"]})
        time.sleep(0.12)
    if verbose:
        print(f"  {len(cache['schools'])} schools cached", file=sys.stderr)

    cache["built_at"] = time.strftime("%Y-%m-%d %H:%M")
    save_cache(cache)
    return cache


# ─────────────────────────────────────────────────────────────
#  Analysis
# ─────────────────────────────────────────────────────────────

def analyse(args):
    cache = load_cache()
    if args.refresh or not cache.get("stations"):
        print("Building OneMap coordinate cache (one-off) ...", file=sys.stderr)
        cache = build_cache()

    term = args.address or args.project
    if not term:
        return {"error": "Pass --project or --address."}

    site = geocode(term)
    if not site:
        return {"error": f"OneMap could not locate '{term}'."}

    token = args.token or os.environ.get("ONEMAP_TOKEN")
    origin = (site["lat"], site["lng"])

    stations = []
    for s in cache["stations"]:
        d = haversine_m(site["lat"], site["lng"], s["lat"], s["lng"])
        if d <= args.radius:
            stations.append({
                "station": s["station"],
                "codes": s["codes"],
                "straight_line_m": round(d),
                "est_walk_m": round(d * WALK_FACTOR),
                "est_walk_min": round(d * WALK_FACTOR / WALK_SPEED_M_PER_MIN, 1),
            })
    stations.sort(key=lambda x: x["straight_line_m"])
    stations = stations[:args.limit]

    for s in stations[:3]:
        node = next(c for c in cache["stations"] if c["station"] == s["station"])
        exact = walking_route_m(token, origin, (node["lat"], node["lng"]))
        if exact:
            s["walk_route_m"] = exact
            s["walk_route_min"] = round(exact / WALK_SPEED_M_PER_MIN, 1)

    schools = []
    for sc in cache.get("schools", []):
        d = haversine_m(site["lat"], site["lng"], sc["lat"], sc["lng"])
        if d <= 2000:
            schools.append({
                "school": sc["school"],
                "distance_m": round(d),
                "within_1km": d <= 1000,
                "within_2km": d <= 2000,
            })
    schools.sort(key=lambda x: x["distance_m"])

    nearest = stations[0] if stations else None
    walk = (nearest or {}).get("walk_route_m") or (nearest or {}).get("est_walk_m")
    inside_1km = [s for s in schools if s["within_1km"]]

    return {
        "site": site,
        "token_used": bool(token),
        "nearest_mrt": nearest,
        "mrt_within_radius": stations,
        "mrt_verdict": (
            "no station within the search radius" if not nearest else
            "integrated / direct link" if walk <= 150 else
            "excellent — well inside Eric's 400-500 m rule" if walk <= 300 else
            "passes Eric's 400-500 m rule" if walk <= 500 else
            "borderline" if walk <= 700 else
            "fails the MRT rule" if walk <= 1000 else
            "hard veto — over 1 km, 'will break your legs'"
        ),
        "elite_schools_within_1km": inside_1km,
        "elite_schools_nearby": schools,
        "school_verdict": (
            f"{len(inside_1km)} elite primary school(s) inside 1 km" if inside_1km else
            "no elite primary inside 1 km — no desperate-parent price floor"
        ),
        "cache_built_at": cache.get("built_at"),
        "caveat": (
            "Straight-line distance x1.25. Set ONEMAP_TOKEN for true walking routes."
            if not token else "Walking distances are true OneMap routes for the top 3 stations."
        ),
    }


def render(res):
    if "error" in res:
        print(res["error"])
        return
    s = res["site"]
    print(f"\nSITE     {s['name']}")
    print(f"         {s['address']}")
    print(f"         {s['lat']:.6f}, {s['lng']:.6f}")
    if s.get("alternatives"):
        print(f"         other OneMap hits: {', '.join(a for a in s['alternatives'] if a)}")

    print(f"\nMRT      {res['mrt_verdict']}")
    for st in res["mrt_within_radius"]:
        exact = f"  (route {st['walk_route_m']} m / {st['walk_route_min']} min)" if st.get("walk_route_m") else ""
        print(f"  {st['station']:<26} {'/'.join(st['codes']):<14} "
              f"{st['straight_line_m']:>5} m straight  ~{st['est_walk_m']:>5} m walk "
              f"({st['est_walk_min']} min){exact}")

    print(f"\nSCHOOLS  {res['school_verdict']}")
    for sc in res["elite_schools_nearby"][:6]:
        mark = "IN 1km" if sc["within_1km"] else "      "
        print(f"  {mark}  {sc['school']:<40} {sc['distance_m']:>5} m")

    print(f"\n{res['caveat']}\n")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project", help="Project or building name")
    p.add_argument("--address", help="Street address or postal code (more precise than a name)")
    p.add_argument("--radius", type=int, default=1500, help="MRT search radius in metres")
    p.add_argument("--limit", type=int, default=5, help="Max stations to report")
    p.add_argument("--token", help="OneMap API token (or set ONEMAP_TOKEN)")
    p.add_argument("--refresh", action="store_true", help="Rebuild the station/school cache")
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
