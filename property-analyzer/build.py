#!/usr/bin/env python3
"""
build.py — prepare the Property Analyzer for deployment.

Locally the app reaches up a directory for whichever ura_data.js is newest. A deployment has
no parent directory, so the dataset has to travel with the page. This script:

  1. finds the freshest dataset among the known copies
  2. dictionary-encodes it (roughly 60% smaller — that matters in git history)
  3. writes it to property-analyzer/ura_data.js, which IS committed so Vercel can
     deploy straight from GitHub with the root directory set to property-analyzer/
  4. also writes property-analyzer/dist/ for a CLI deploy

    python property-analyzer/build.py

    # deploy from git: commit the refreshed ura_data.js and push
    # deploy from CLI: cd property-analyzer/dist && npx vercel deploy --prod

Re-run after every data refresh — the committed file is a snapshot, not a link.
"""

import json
import os
import shutil
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DIST = os.path.join(HERE, "dist")

# Same candidates the browser probes, newest wins.
CANDIDATES = [
    os.path.join(ROOT, "ura_data.js"),          # Fetch-UraData.ps1 default output
    os.path.join(ROOT, "FetchURA", "ura_data.js"),
    os.path.join(ROOT, "Netlify upload_property", "ura_data.js"),
    os.path.join(ROOT, "House", "ura_data.js"),
    os.path.join(HERE, "ura_data.js"),
]

VERCEL_CONFIG = {
    "cleanUrls": True,
    "headers": [
        {
            # The dataset is a content-addressed snapshot per deploy — cache it hard.
            "source": "/ura_data.js",
            "headers": [{"key": "Cache-Control", "value": "public, max-age=86400"}],
        },
        {
            "source": "/index.html",
            "headers": [{"key": "Cache-Control", "value": "no-cache"}],
        },
    ],
}


def newest_dataset():
    found = [(os.path.getmtime(p), p) for p in CANDIDATES if os.path.exists(p)]
    if not found:
        sys.exit("No ura_data.js found. Run your fetch script first.")
    found.sort(reverse=True)
    return found[0][1], datetime.fromtimestamp(found[0][0])


def stamp_of(path):
    """The date the fetch script wrote into the file's first line."""
    with open(path, encoding="utf-8") as fh:
        first = fh.readline()
    for token in first.replace("—", "-").split():
        if len(token) == 10 and token[4] == "-" and token[7] == "-":
            return token
    return "unknown"


# Columns worth dictionary-encoding: low cardinality, repeated on every row.
DICT_COLS = ["project", "district", "tenureType", "tenure", "bedroomType", "sizeBand",
             "marketSegment", "propertyType", "floorRange", "saleType"]


def compact(src_path, stamp):
    """Replace repeated strings with indices into a per-column lookup table.

    The page already understands both shapes: a `meta` block means the row values are
    indices, its absence means they are literals.
    """
    with open(src_path, encoding="utf-8") as fh:
        raw = fh.read()
    blob = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    cols, rows = blob["cols"], blob["rows"]

    if blob.get("meta"):
        return raw, len(rows), False        # already compact, pass it through

    idx = {c: i for i, c in enumerate(cols)}
    meta, lookup = {}, {}
    for col in DICT_COLS:
        if col not in idx:
            continue
        vals = sorted({r[idx[col]] for r in rows}, key=str)
        meta[col] = vals
        lookup[col] = {v: i for i, v in enumerate(vals)}

    for r in rows:
        for col, table in lookup.items():
            r[idx[col]] = table[r[idx[col]]]

    payload = {"cols": cols, "rows": rows, "meta": meta}
    if blob.get("fetchedAt"):
        payload["fetchedAt"] = blob["fetchedAt"]
    out = (f"// URA Real Data (compact) - {stamp} - {len(rows)} records\n"
           "window.URA_DATA=" + json.dumps(payload, separators=(",", ":")) + ";")
    return out, len(rows), True


def main():
    src, mtime = newest_dataset()
    index = os.path.join(HERE, "index.html")
    if not os.path.exists(index):
        sys.exit(f"index.html missing at {index}")

    stamp = stamp_of(src)
    before = os.path.getsize(src) / 1_048_576
    data, n, did_compact = compact(src, stamp)

    # The committed copy — this is what a git-based deploy serves.
    committed = os.path.join(HERE, "ura_data.js")
    with open(committed, "w", encoding="utf-8") as fh:
        fh.write(data)

    # Clear dist's contents but never the directory itself: Windows refuses to rmdir a
    # folder another process has open (the Vercel CLI, a shell sitting in it), and a
    # half-deleted dist is worse than none — you can end up deploying an empty site.
    # Keep .vercel too: it is the project link, and losing it makes the CLI ask
    # "Which project?" again, which is how duplicate projects get created.
    had_link = os.path.isdir(os.path.join(DIST, ".vercel"))
    os.makedirs(DIST, exist_ok=True)
    for name in os.listdir(DIST):
        if name == ".vercel":
            continue
        victim = os.path.join(DIST, name)
        if os.path.isdir(victim):
            shutil.rmtree(victim)
        else:
            os.remove(victim)

    shutil.copy2(index, os.path.join(DIST, "index.html"))
    shutil.copy2(committed, os.path.join(DIST, "ura_data.js"))
    with open(os.path.join(DIST, "vercel.json"), "w", encoding="utf-8") as fh:
        json.dump(VERCEL_CONFIG, fh, indent=2)

    after = os.path.getsize(committed) / 1_048_576
    rel = os.path.relpath(src, ROOT)

    print(f"Source      {rel}")
    print(f"            stamp {stamp}, written {mtime:%Y-%m-%d %H:%M}, "
          f"{n:,} records, {before:.1f} MB")
    if did_compact:
        print(f"Compacted   {before:.1f} MB -> {after:.1f} MB "
              f"({(1 - after/before)*100:.0f}% smaller)")
    else:
        print("Compacted   already dictionary-encoded, passed through")
    print(f"Wrote       property-analyzer/ura_data.js   (committed — git deploys serve this)")
    print(f"            property-analyzer/dist/         (index.html + data + vercel.json)")
    if had_link:
        print(f"            dist/.vercel preserved — the deploy stays linked to its project")
    if after > 90:
        print("\n  WARNING: over 90 MB — Vercel's static file limit is 100 MB.")
    print("\nDeploy from git:  git add property-analyzer/ura_data.js && git commit && git push")
    print("Deploy from CLI:  cd property-analyzer/dist && npx vercel deploy --prod")


if __name__ == "__main__":
    main()
