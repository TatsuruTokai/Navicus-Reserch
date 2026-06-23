# NAVICUS Research Pages

Static GitHub Pages export for NAVICUS municipal SNS/proposal research.

## Release rule

Only Release-GO runs may be published.

The exporter stops unless this file exists and says `decision: GO`:

```text
out/navicus_filtered/YYYY-MM-DD/release_go_decision_v12_4.json
```

## Daily update flow

1. Run the daily research and DB reflection workflow.
2. Repeat validation until the release decision is `GO`.
3. Export the static Pages bundle:

```bash
python3 tools/navicus_pages/export_static_pages.py --run-date YYYY-MM-DD --run-label manual_research --root-redirect
```

4. Validate `Navicus-Reserch/data/index.json` and the gzip snapshot.
5. Commit and push the updated `Navicus-Reserch/`, `index.html`, `.nojekyll`, and exporter changes.

## Public structure

```text
index.html
.nojekyll
Navicus-Reserch/
  index.html
  assets/app.js
  data/index.json
  data/latest.json
  data/runs/YYYY-MM-DD/<run-label>/
    snapshot.json.gz
    release_go_decision_v12_4.json
    quality_report.json
    csv_go_audit_report.json
    top20_precision_report.json
    known_positive_replay_report.json
    schema_preflight_report.json
    wave_status.json
tools/navicus_pages/export_static_pages.py
```
