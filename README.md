# Queensland Web Business Finder — Overture Maps

Free, repeatable candidate sourcing for LocalWebDesigner.com.au using Overture Maps Places.

## What it does

- Queries the latest Overture release directly from its public cloud-hosted GeoParquet data.
- Limits results to Australia / Queensland (`AU-QLD`).
- Requires a website and ignores permanently closed places.
- Filters broadly for web, digital, marketing, advertising, software, design and technology businesses.
- Applies a second relevance score in Python.
- Deduplicates by domain and excludes domains already in `config/exclude_domains.txt`.
- Writes `output/qld_web_candidates.csv`.

The output intentionally remains a **candidate list**. Before publishing to Local Web Designer, continue the existing workflow: verify directory relevance, map region/locality, retrieve the business website's current meta description, keep claim/verification fields unclaimed/unverified unless actually verified, then import.

## Run with GitHub Actions

1. Put these files in a GitHub repository.
2. Open **Actions** → **Build Queensland web-business list**.
3. Click **Run workflow**.
4. When the job completes, open `output/qld_web_candidates.csv` in the repository.

The workflow also runs weekly and commits a refreshed CSV when results change.

## Run locally

```bash
python -m pip install duckdb
python scripts/overture_qld.py
```

## Important data notes

Overture Places contains open place/business data from multiple providers. Confidence and category are useful screening signals, not proof that a company belongs in the Local Web Designer directory. The script deliberately keeps a review step instead of auto-publishing results.

Source: Overture Maps Foundation Places dataset.
