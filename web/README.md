# Kolekcjoner Fejków: web UI

Next.js (App Router, TypeScript) front end over the read-only API in
`src/fakecollector/api/`. All data comes from an analysed run directory; nothing from the
corpora is bundled here.

```bash
# API on 127.0.0.1:8600 (needs the `web` extra, plus `ml` for /api/assign)
APP_RUN_DIR=runs/dev uv run --extra web --extra ml fakecollector-web
# UI on :3000; /api/* is rewritten to the API (KF_API_URL overrides the target)
cd web && npm ci && npm run build && npx next start -p 3000
```

Pages: overview (`/`), campaign (`/campaigns/[id]`), case (`/cases/[id]`),
analyse new material (`/analyze`), campaign graph (`/graph`), methodology (`/methodology`).
The API serves artifacts only as re-encoded JPEG thumbnails, never corpus HTML or scripts,
and never fetches URLs taken from inputs. Evaluation numbers on `/methodology` are copied from
`docs/METHODOLOGY.md` §9 into `src/data/evaluation.json`.

Graph: a deterministic 2D campaign map (d3-force, operator clusters) and a case × shared-trace
matrix per campaign. Animations use Motion and respect `prefers-reduced-motion`. Third-party
licenses: [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md).
