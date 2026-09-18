#!/usr/bin/env python3
import csv
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import duckdb

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "qld_web_candidates.csv"
EXCLUDE = ROOT / "config" / "exclude_domains.txt"

QLD_BBOX = (137.99, -29.20, 153.56, -9.10)
MAX_RAW = 8000
MAX_OUTPUT = 3000
MIN_CONFIDENCE = 0.60

STRONG_CATEGORY_TERMS = {
    "web", "website", "internet", "digital", "software", "computer",
    "marketing", "advertis", "graphic", "design", "ecommerce", "e-commerce",
    "app", "technology", "seo", "media"
}
STRONG_NAME_TERMS = {
    "web", "digital", "creative", "marketing", "media", "design", "agency",
    "software", "tech", "technology", "seo", "ecommerce", "e-commerce",
    "interactive", "online", "internet", "apps", "studio"
}
NEGATIVE_TERMS = {
    "interior design", "fashion design", "landscape design", "hair design",
    "nail design", "kitchen design", "building design", "jewellery design",
    "jewelry design", "architectural design", "signwriter", "printing only"
}


def norm_domain(value: str) -> str:
    value = (value or "").strip().lower()
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    p = urlparse(value)
    host = (p.netloc or p.path.split("/")[0]).split(":")[0]
    return host.removeprefix("www.").rstrip(".")


def norm_url(value: str) -> str:
    d = norm_domain(value)
    return f"https://{d}/" if d else ""


def load_excludes() -> set[str]:
    if not EXCLUDE.exists():
        return set()
    return {norm_domain(x) for x in EXCLUDE.read_text(encoding="utf-8").splitlines() if norm_domain(x)}


def latest_release() -> str:
    with urllib.request.urlopen("https://stac.overturemaps.org/catalog.json", timeout=30) as r:
        import json
        data = json.load(r)
    latest = data.get("latest")
    if not latest:
        raise RuntimeError("Could not determine latest Overture release from STAC catalog")
    return latest


def score(name: str, category: str, hierarchy: str) -> int:
    n = (name or "").lower()
    c = (category or "").replace("_", " ").lower()
    h = (hierarchy or "").replace("_", " ").lower()
    joined = f"{n} {c} {h}"
    if any(x in joined for x in NEGATIVE_TERMS):
        return -10
    s = 0
    for term in STRONG_CATEGORY_TERMS:
        if term in c or term in h:
            s += 2
    for term in STRONG_NAME_TERMS:
        if term in n:
            s += 1
    # Favor clearly directory-relevant categories.
    for phrase in ("website", "web design", "web development", "digital marketing",
                   "marketing agency", "advertising agency", "software", "seo"):
        if phrase in joined:
            s += 3
    return s


def main() -> int:
    release = latest_release()
    print(f"Using Overture release: {release}")

    con = duckdb.connect()
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    con.execute("SET s3_region='us-west-2'")

    path = f"s3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*"
    xmin, ymin, xmax, ymax = QLD_BBOX

    # Keep the server-side predicate intentionally broad. Python performs a second
    # relevance pass so schema/category changes do not silently eliminate good leads.
    query = f"""
    SELECT
      id,
      names.primary AS business_name,
      websites[1] AS website,
      phones[1] AS phone,
      emails[1] AS email,
      addresses[1].freeform AS address,
      addresses[1].locality AS locality,
      addresses[1].postcode AS postcode,
      addresses[1].region AS region,
      addresses[1].country AS country,
      taxonomy.primary AS category,
      CAST(taxonomy.hierarchy AS VARCHAR) AS category_hierarchy,
      confidence,
      operating_status
    FROM read_parquet('{path}', filename=true, hive_partitioning=1)
    WHERE
      bbox.xmin BETWEEN {xmin} AND {xmax}
      AND bbox.ymin BETWEEN {ymin} AND {ymax}
      AND addresses[1].country = 'AU'
      AND addresses[1].region IN ('QLD', 'AU-QLD')
      AND websites IS NOT NULL
      AND confidence >= {MIN_CONFIDENCE}
      AND (operating_status IS NULL OR operating_status <> 'permanently_closed')
      AND (
        taxonomy.primary ILIKE '%web%'
        OR taxonomy.primary ILIKE '%internet%'
        OR taxonomy.primary ILIKE '%digital%'
        OR taxonomy.primary ILIKE '%marketing%'
        OR taxonomy.primary ILIKE '%advertis%'
        OR taxonomy.primary ILIKE '%software%'
        OR taxonomy.primary ILIKE '%computer%'
        OR taxonomy.primary ILIKE '%graphic%'
        OR taxonomy.primary ILIKE '%design%'
        OR taxonomy.primary ILIKE '%media%'
        OR taxonomy.primary ILIKE '%technology%'
      )
    ORDER BY confidence DESC
    LIMIT {MAX_RAW}
    """

    rows = con.execute(query).fetchall()
    cols = [d[0] for d in con.description]
    excludes = load_excludes()
    seen = set(excludes)
    selected = []

    for raw in rows:
        r = dict(zip(cols, raw))
        name = (r.get("business_name") or "").strip()
        domain = norm_domain(r.get("website") or "")
        if not name or not domain or domain in seen:
            continue
        relevance = score(name, r.get("category") or "", r.get("category_hierarchy") or "")
        if relevance < 3:
            continue
        seen.add(domain)
        selected.append({
            "overture_id": r.get("id") or "",
            "business_name": name,
            "website_url": norm_url(domain),
            "phone": r.get("phone") or "",
            "email_public": r.get("email") or "",
            "address": r.get("address") or "",
            "locality": r.get("locality") or "",
            "postcode": r.get("postcode") or "",
            "region": r.get("region") or "",
            "country": r.get("country") or "",
            "overture_category": r.get("category") or "",
            "overture_category_hierarchy": r.get("category_hierarchy") or "",
            "overture_confidence": r.get("confidence") or "",
            "relevance_score": relevance,
            "source_type": "overture-maps",
            "source_release": release,
        })

    selected.sort(key=lambda x: (-int(x["relevance_score"]), -float(x["overture_confidence"] or 0), x["business_name"].lower()))
    selected = selected[:MAX_OUTPUT]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fields = list(selected[0].keys()) if selected else [
        "overture_id","business_name","website_url","phone","email_public","address",
        "locality","postcode","region","country","overture_category",
        "overture_category_hierarchy","overture_confidence","relevance_score",
        "source_type","source_release"
    ]
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(selected)

    print(f"Raw candidates scanned: {len(rows)}")
    print(f"Excluded known domains: {len(excludes)}")
    print(f"New candidates written: {len(selected)}")
    print(f"Output: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
