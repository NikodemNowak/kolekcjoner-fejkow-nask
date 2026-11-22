# Kolekcjoner Fejków

HackNation 2026, NASK task "Kolekcjoner Fejków": linking scam ads and fake pages into campaigns, with evidence.

## Co to robi

Narzędzie przyjmuje materiały z podejrzanych reklam (adres URL, zrzut ekranu, log HAR, zapisaną stronę MHTML, PDF, wideo, cały folder zgłoszenia albo nazwę produktu lub tekst), wyciąga z nich cechy (tekst, obrazy, twarze osób publicznych, logotypy, identyfikatory śledzące, infrastrukturę, strukturę strony) i łączy zgłoszenia w **kampanie** oraz **operatorów**. Każde powiązanie ma wyjaśnienie: pokazujemy, które ślady je uzasadniają i jak mocne są. Nowy materiał jest porównywany ze znanym zbiorem i dostaje jedną z trzech odpowiedzi: **wariant istniejącej kampanii**, **nowy wzorzec** albo **do weryfikacji** (gdy dowody są zbyt słabe, żeby zgadywać). Całość działa lokalnie na CPU, bez kluczy API i bez odwiedzania adresów z materiałów; interfejs (Next.js) jest po polsku.

Kolekcjoner Fejków groups reports of scam ads and landing pages into campaigns and shows the evidence behind every link. New material is compared with a known set and answered as `existing campaign`, `new pattern` or `needs review`.


## For the jury: run in 3 commands

**Quick start (Docker).**

Everything runs on **CPU**, with no GPU, no API key and no account. The network is needed only at build time (Python wheels, model weights from Hugging Face, reference photos from Wikimedia Commons). The container has the models (SigLIP2, EasyOCR, InsightFace, bge-m3) and the reference sets built in.

```bash
mkdir -p runs                                               # must exist, so the container can write to it
docker compose build                                        # once; API + UI; needs network; ~20 min from a clean cache
docker compose run --rm app fakecollector demo --fixtures   # smoke test on the synthetic cases in ./data/fixtures
APP_RUN_DIR=runs/demo docker compose up                     # UI on http://localhost:3000
```

The UI shows overview, campaigns, case pages with evidence, the campaign map, the **Analizuj** page (assign new material) and a methodology page. The API listens on `127.0.0.1:8600`.

### What the jury machine needs

- **Docker** Engine 24+ with Compose v2 (`docker compose`), or Docker Desktop; x86-64.
- **No GPU** (`FAKECOLLECTOR_DEVICE=cpu`, CPU builds of PyTorch and ONNX Runtime).
- **Disk:** image about 6 GB (Docker Desktop with the containerd image store can report up to about 16 GB); keep **20 GB free** for the build. **RAM:** 8 GB is enough (the `full` profile on both development corpora peaked at 2.6 GB in the container).
- **Network** only while building. Running needs none: `docker run --network none` works.
- **Build time** about **20 min** from a clean cache (measured on a 20-thread desktop): about 10 min fetching 172 reference photos from Wikimedia Commons (rate-limited), 2–3 min model weights, 3–4 min image layers. Later builds reuse the cache.
- **Build options:** `--build-arg WITH_BGE=0` leaves out bge-m3 (about 2 GB smaller; `text.bge` is skipped with a warning). `--build-arg WITH_ML=0` builds a light image with no models (hashing, HTML, HAR and graph features only).

### Isolated environment (YAML manifests)

Hardened Docker Compose override (`docker-compose.secure.yml`: no internet for the API, no capabilities, read-only UI, limits, localhost only) and Kubernetes manifests (`deploy/k8s/`: Pod Security `restricted`, NetworkPolicies with no egress, non-root pods, a Job that builds the base). Step-by-step: [deploy/README.md](deploy/README.md).

## Running on your own data

Organizer data is supplied by the jury and is mounted read-only under `./data`. Material the repository does not contain must be placed there.

**1. Build a run on the known set** (a folder of case folders; one case = one report of an ad and what it led to):

```bash
docker compose run --rm app fakecollector run data/<known> --out runs/base --profile full
```

**2. Assign new material against it**, from the CLI or from the UI:

```bash
docker compose run --rm app fakecollector assign data/<new> --against runs/base
docker compose up                       # UI on http://localhost:3000 serves runs/base (APP_RUN_DIR default)
```

In the UI open **Analizuj** and upload files or paste a URL / product name / text; the rule is the same as for `assign`. Another run: `APP_RUN_DIR=runs/<name> docker compose up`.

**Accepted inputs:** a case folder; a single file (screenshot, HAR network log, MHTML or HTML saved page, PDF printout, video); a URL; a product name or free text. **A URL is only parsed (domain, parameters), never visited.** `assign` writes `assignments.csv` and `assignments.html` into the run directory; add `--commit` to store the new cases in the run without renumbering existing campaigns.

Each answer is one of **wariant kampanii X** (with the evidence), **nowy wzorzec** (optionally with a known operator or toolkit) or **do weryfikacji**.

Other commands (`fakecollector --help`): `ingest`, `extract`, `analyze` (the stages of `run` separately), `report <run>` (self-contained HTML report with the interactive campaign graph), `export <run> --format json|neo4j|gexf|graphml|ioc-csv|dataset` (the `dataset` export contains the derived data; do not share it publicly when it comes from organizer data). The default `--profile fast` skips the ML extractors; the container image supports `--profile full`.

**Fully offline check:**

```bash
docker run --rm --network none -v "$PWD/data:/app/data:ro" -v "$PWD/runs:/app/runs" fakecollector \
  fakecollector assign data/<new> --against runs/base
```

## How it works

Details and every threshold: [docs/METHODOLOGY.md](docs/METHODOLOGY.md).

1. **Ingest.** A case folder is read into typed artifacts (HAR, HTML, assets, screenshots, video, PDF, metadata). Nothing is executed or fetched.
2. **Feature families.** Extractors turn artifacts into comparable features: identifiers and trackers (`ids`), infrastructure (`infra`), exact file hashes (`asset`), page template (`template`), images (pHash/PDQ, SigLIP2, local geometric matching), text (MinHash, fuzzy headlines, bge-m3, OCR, speech-to-text) and public-figure faces and brand logos (`person`).
3. **Evidence graph with tiers.** A typed entity graph keeps where each observation came from. Cases are linked only when campaign-specific evidence is strong enough; shared infrastructure, reusable kits and contextual clues are reported at their own tiers and do not merge campaigns by themselves. Weights stay documented priors, not learned.
4. **Campaigns and operators.** Leiden clustering on the weighted case graph gives campaigns; operator links group campaigns. Every group gets a common-traits profile.
5. **Open-set decision.** A new case is scored against each known campaign and answered `existing`, `new` or `review` with a Polish explanation of the evidence. A wrong automatic match is treated as worse than sending a case to review.

## Results

On the two NASK development corpora (25 reports, team gold labels, strict, `full` profile): campaign pairwise **P 1.000 / R 0.947 / F1 0.973**, operator F1 **1.000**; open set: held-out variant **100 %**, leave-one-campaign-out **92 %** with **0 % false accepts**, cross-corpus **90 %** with **0 % false accepts**. Full tables, ablations, sparse-input and degraded-input tests and the protocol: [docs/results.md](docs/results.md) and [METHODOLOGY §9](docs/METHODOLOGY.md#9-evaluation).

Sparse input, assignment of one variant as a single file (hidden-test simulation): saved page 8/8, HAR 7/8, PDF 7/8, degraded screenshots 15/17.

**Runtime** on both development corpora (25 cases, 406 images, 87 keyframes): full vision profile on CPU 342 s in the container; base features without models 66 s; clustering under 1 s. On an RTX 5080 the same run takes 69 s for the vision stage (CPU and GPU features match; [docs/benchmark-vision.md](docs/benchmark-vision.md)).

**Limitations (honest):**
- Only 25 development cases. With 0 false accepts in 25 leave-one-out trials, the one-sided 95 % upper bound on the false-accept rate is about 11 %; thresholds are priors, not calibrated on a large independent set.
- Screenshot-only and video-only material rarely carries enough campaign-specific evidence on its own (campaign F1 0.100 and 0.000 in the input ablation); such cases usually link only through a near-duplicate image or go to review.
- A sibling ad that changes both creative and wording cannot be linked offline; only its landing page would connect it. The system then answers "nowy wzorzec" or "za mało danych" instead of guessing.
- Under lenient labels for one disputed campaign, leave-one-out FAR is 8 % and cross-corpus FAR 12.5 % (both are the same disputed pair).
- Face matching covers a small reference set of public figures (48 people); logos cover 34 brands.

## Incomplete data

Missing or broken inputs never stop a run. Families missing on one side add no evidence and no penalty; dead pages and capture errors are flagged (`capture_error`); a HAR filed under the wrong case is re-attached by landing host; corrupt or oversized files are skipped with a warning per file; screenshot-only, video-only and URL-only cases are flagged and use whatever evidence they have (OCR, keyframes, ASR, URL parameters); cloaking (different pages under one URL) is flagged for review. A thin submission can still link through one strong pair, go to review, or start a new campaign. Table: [METHODOLOGY §8](docs/METHODOLOGY.md#8-incomplete-and-messy-input).

## Public-source collector and scheduler (optional, needs network)

`fakecollector collect` looks for new articles about scam ads at fact-checkers and CERT-type publishers (`demagog`, `fakenews`, `cert`, `niebezpiecznik`; RSS feeds), saves the ad screenshots embedded in those articles as case folders and assigns each one against a run:

```bash
uv run fakecollector collect --run runs/base --sources demagog,cert --since 2026-11-01           # dry run
uv run fakecollector collect --run runs/base --sources all --since 2026-11-01 --commit  # add to the run
uv run fakecollector watch --run runs/base --every 6h --commit                          # periodic update
```

In Docker prefix with `docker compose run --rm app` (needs the default network, not `--network none`).

- It fetches only the publisher's feed, article pages and images hosted by the publisher; images hosted elsewhere and every scam URL quoted in an article are never requested. It respects `robots.txt`, waits at least 1 s between requests and uses a generic User-Agent.
- Each pass writes `<run>/collector/last.json` (items, decision `existing` / `review` / `new`, campaign, score, evidence; read by the UI), `history/<time>.json`, `items.jsonl` and `seen.json`. Case folders land in `<run>/collector/inbox/`.
- Without network it prints "Brak połączenia z siecią" and exits with code 2; nothing else changes.
- `watch` is a plain loop (`--iterations N` to stop); for production use cron or a systemd timer calling `collect`. Collected material is third-party content: keep it local, do not redistribute.

## Configuration

All settings are environment variables; none is required. `docker-compose.yml` reads `.env.example`; for a local install, copy it to `.env`.

| Variable | Default | Meaning |
|---|---|---|
| `APP_DATA_DIR` | `./data` | Root of the input data. |
| `APP_LOG_LEVEL` | `INFO` | Log level. |
| `APP_MAX_ARTIFACT_MB` | `2048` | Larger files are skipped with a warning. |
| `APP_RUN_DIR` | `runs/base` in compose | Run directory the web UI/API serves. |
| `KF_API_URL` | `http://127.0.0.1:8600` | Where the web UI reaches the API. |
| `KF_DEMO_USER`, `KF_DEMO_PASSWORD` | unset | Optional basic-auth gate for a public demo of the web UI; unset means open. |
| `FEATURE_CACHE` | `~/.cache/fakecollector/features` | Per-artifact feature cache; a second run over the same files is near-instant. |
| `ALLOW_ENRICH` | `false` | Opt-in passive enrichment (DNS over HTTPS, Team Cymru ASN, RDAP, crt.sh, CERT Polska warning list). Off by default; a run never needs the network. |
| `FAKECOLLECTOR_DEVICE` | auto (`cuda` if available) | `cpu` forces CPU. The image sets `cpu`. |
| `FAKECOLLECTOR_ASR` | on | `0` turns off speech-to-text of videos. |
| `FAKECOLLECTOR_ASR_MODEL` | `turbo` on GPU, `small` on CPU | faster-whisper model name. |
| `FACE_DB`, `LOGO_REFS` | `data/faces/db.npz`, `data/logos/refs.npz` | Face and logo reference vectors. The image sets them to the copies built in. |
| `FACE_BACKEND` | `insightface` | Face embedder (swappable, see the licence notes below). |

## Local install without Docker

Python 3.12 + [uv](https://docs.astral.sh/uv/), Node 22, ffmpeg on `PATH` (video).

```bash
uv sync --extra web --extra ml --extra bge        # first run downloads the models
uv run fakecollector demo --fixtures              # writes runs/demo/report.html
APP_RUN_DIR=runs/demo uv run --extra web --extra ml fakecollector-web   # API on 127.0.0.1:8600
cd web && npm ci && npm run build && npx next start -p 3000             # UI on http://localhost:3000
```

The face DB and logo references are built with `scripts/fetch_face_refs.py`, `scripts/build_face_db.py` and `scripts/build_logo_refs.py` (the Docker build does this for you). A GPU is used automatically when CUDA PyTorch is installed. More on the UI: [web/README.md](web/README.md). Before pushing: `make check` (ruff, mypy, pytest).

## Project layout

```
src/fakecollector/
  cli.py, pipeline.py   CLI (run, assign, collect, watch, report, export) and the stage pipeline
  ingest/               case folders, HAR parsing, normalisation into typed artifacts
  extractors/           feature extractors: ids, infra, assets, template, text, OCR, images, faces, brands, PDF, ad-library metadata
  graph/                entity graph, fusion of evidence, tiers, clustering, traits profiles, open-set assignment
  enrich/               opt-in passive enrichment (DNS over HTTPS, RDAP, crt.sh, warning list)
  collect/              public-source collector (RSS fact-checkers / CERT) behind `collect` and `watch`
  evaluation/           gold labels, metrics, open-set protocol, calibration
  export/               json, Neo4j, GEXF/GraphML, IOC CSV, dataset
  report/               self-contained HTML report with the Cytoscape graph
  api/                  read-only FastAPI service behind the web UI (assignment and uploads)
  app/                  legacy optional Streamlit app (`fakecollector app`); the main UI is web/
  core/, models.py, store.py, config.py   extractor registry, data schemas, run storage, settings
web/                    Next.js UI (overview, campaigns, cases, graph, Analizuj, methodology)
tests/                  pytest suite (synthetic data only)
scripts/                evaluation (evaluate.py), reference-set builders, benchmarks, fixtures generator
docs/                   METHODOLOGY.md, results.md, benchmark-vision.md and other method notes
data/fixtures/          synthetic demo cases (organizer data goes under ./data, git-ignored)
```

## Credits & licenses
| Component | License | Used for |
|---|---|---|
| pydantic, pydantic-settings | MIT | data contract, config |
| Typer | MIT | CLI |
| Streamlit | Apache-2.0 | legacy optional app (`fakecollector app`); the main UI is the Next.js web app |
| FastAPI, Uvicorn, python-multipart | MIT / BSD-3-Clause / Apache-2.0 | read-only web API (`web` extra) |
| Next.js, React | MIT | web UI (`web/`) |
| Tailwind CSS, shadcn/ui, Radix UI | MIT | web UI components |
| lucide-react | ISC | web UI icons |
| next-themes | MIT | light/dark mode |
| Motion (motion/react) | MIT | web UI animations |
| d3-force, d3-zoom, d3-selection, d3-transition | ISC | campaign map layout, zoom and pan |
| Web UI dependencies (full list) | MIT / ISC / Apache-2.0 / BSD / OFL | see [`web/THIRD_PARTY_LICENSES.md`](web/THIRD_PARTY_LICENSES.md) |
| Geist, Geist Mono | SIL OFL 1.1 | web UI fonts |
| Jinja2 | BSD-3-Clause | HTML report |
| Cytoscape.js 3.30.4 | MIT | Offline interactive report graph; license in `src/fakecollector/report/static/CYTOSCAPE-LICENSE` |
| DuckDB | MIT | queries over run tables |
| PyArrow | Apache-2.0 | Parquet storage |
| NumPy | BSD-3-Clause | Vector storage and numerical arrays |
| NetworkX | BSD-3-Clause | Operator grouping and Louvain campaign clustering |
| python-igraph, leidenalg | GPL-2.0-or-later / GPL-3.0-or-later | Default Leiden campaign clustering. Select `EdgeConfig(cluster_algo="louvain")` to use NetworkX. |
| Beautiful Soup, lxml | MIT / BSD-3-Clause | HTML parsing |
| tldextract | BSD-3-Clause | registrable domains |
| datasketch | MIT | Text MinHash signatures and candidate blocking |
| [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) | MIT | Optional dense text embeddings. Retain the license notice if redistributing. |
| [Sentence Transformers](https://github.com/huggingface/sentence-transformers/blob/main/LICENSE) | Apache-2.0 | Optional runtime for BGE-M3. License and notice terms apply to redistribution. |
| PyYAML | MIT | Optional parsing of YAML stoplists |
| ImageHash | BSD-2-Clause | perceptual hashes |
| mmh3 | MIT | favicon hashes |
| stix2 | BSD-3-Clause | STIX 2.1 export |
| Public Suffix List (snapshot bundled in tldextract) | MPL-2.0 | registrable domains, offline |
| Cloudflare and Fastly published edge IP ranges (cloudflare.com/ips, api.fastly.com/public-ip-list) | public lists, no terms beyond attribution | CDN stop-list in `graph/stoplist.toml` |
| Cloudflare DNS over HTTPS (`cloudflare-dns.com/dns-query`) | free public resolver, no key; Cloudflare 1.1.1.1 privacy policy | opt-in NS records (`ALLOW_ENRICH=true`) |
| Team Cymru IP-to-ASN mapping (DNS TXT `origin.asn.cymru.com`) | free, no key; keep volume low (bulk users should use their whois service) | opt-in ASN of non-CDN IPs |
| RDAP via `rdap.org` bootstrap redirector | free, no key; each registry's RDAP terms and rate limits apply | opt-in registration month and registrar |
| crt.sh Certificate Transparency search (Sectigo) | free, no key; slow and rate-limited, often returns 5xx/404 under load | opt-in certificate issuers and co-hosted SAN names |
| CERT Polska Lista Ostrzeżeń (`hole.cert.pl/domains/v2/domains.txt`) | public list, free to use with attribution | opt-in "already on the warning list" check |
| InsightFace buffalo_l (models) | **non-commercial research only**; code MIT | face detection + ArcFace embeddings (swappable via `FACE_BACKEND`) |
| google/siglip2-base-patch16-224 | Apache-2.0 | image embeddings, zero-shot brand logos |
| easyocr (pl, en) | Apache-2.0 | OCR of ad screenshots and video keyframes |
| faster-whisper, CTranslate2, PyAV; Whisper `turbo` weights | MIT | speech-to-text of video ads |
| pypdfium2 (PDFium) | Apache-2.0 or BSD-3-Clause (PDFium: BSD-3-Clause / Apache-2.0) | rasterises the first pages of `page.pdf` captures for the vision extractors (no JavaScript); AGPL PyMuPDF deliberately avoided |
| imagehash, pdqhash (Meta PDQ) | BSD-2 / BSD | perceptual image hashes |
| SciPy (`ndimage`) | BSD-3-Clause | creative-region extraction in screenshots |
| OpenCV (`opencv-python-headless`): SIFT, ORB, RANSAC homography | Apache-2.0 (SIFT patent expired 2020) | `local_match` verification of candidate image pairs |
| ffmpeg | LGPL-2.1+ (system binary) | video keyframes, audio decode |
| Wikimedia Commons photos of public figures (`refs/faces.csv`, 48 people, author per row) | CC0 / PD / CC BY 2.0–4.0 / CC BY-SA 2.0–4.0, per file (attribution required for CC BY/BY-SA) | face reference DB (not redistributed; downloaded by script) |
| Wikimedia Commons brand logos (`refs/logos.csv`, 34 brands) | PD (text logos) / CC0; one Gazeta.pl logo CC BY-SA 4.0; trademarks of their owners, used only for detection | impersonated-brand reference set (downloaded by script) |
| Purino/scam-ads-detection-dataset (Hugging Face) | MIT | scam ad images for development |
| kirco567/ScamWeb-Dataset (Hugging Face) | CC-BY-4.0 | scam web pages (MHTML + images), subset |
| RapidFuzz | MIT | fuzzy headline matching (`text.headline_fuzzy`), OCR brand tolerance |
| PyTorch (CPU build in the image) | BSD-3-Clause | runtime for SigLIP2, EasyOCR, bge-m3 |
| Hugging Face Transformers, SentencePiece | Apache-2.0 | SigLIP2 model and tokenizer |
| ONNX Runtime | MIT | InsightFace inference (CPU; `onnxruntime-gpu` optional) |
| insightface (Python package) | MIT (code only; the weights are restricted, see above) | face detection and alignment |
| Whisper `small` weights (CPU default) | MIT | speech-to-text on CPU |
| Pillow | MIT-CMU (HPND) | image decoding |
| HTTPX | BSD-3-Clause | opt-in enrichment HTTP client |
| Meta Ad Library metadata (`yt-dlp` JSON supplied with a case) | parsed offline; collection is subject to Meta's terms | ad archive ID, advertiser and ad copy features |
| Docker base images `python:3.12-slim` (Debian) | PSF-2.0 / Debian package licences | container runtime |
| uv (build tool) | Apache-2.0 / MIT | locked dependency install |
| Neo4j Community (`neo4j:5-community`, optional compose profile) | GPL-3.0 | optional graph-database target for the Neo4j export; not needed to run |
| Hugging Face Hub (model download at build time) | free; anonymous downloads are rate-limited | fetches SigLIP2, bge-m3, Whisper weights once |

### Usage limits that matter

- **InsightFace buffalo_l weights are for non-commercial research only.** Fine for this evaluation; a production deployment at NASK would need a commercial licence from InsightFace or a different `FACE_BACKEND` (the embedder sits behind a protocol, so it can be swapped). Without the face model, the person family is skipped and the rest of the pipeline runs unchanged.
- **Leiden (python-igraph, leidenalg) is GPL.** Using it as a library inside NASK is fine; redistributing a combined product would bring GPL obligations. `EdgeConfig(cluster_algo="louvain")` switches to NetworkX (BSD) with the same graph.
- **Reference photos and logos** come from Wikimedia Commons under per-file licences (listed with author in `refs/faces.csv` and `refs/logos.csv`). They are downloaded at build time and only derived vectors are kept; CC BY / BY-SA files need attribution if redistributed. Logos are trademarks of their owners and are used only to detect impersonation.
- **External services** (all opt-in with `ALLOW_ENRICH=true`, none needs a key): Cloudflare DNS over HTTPS, Team Cymru, RDAP.org (documents 10 requests / 10 s), crt.sh (slow, often 5xx under load), CERT Polska warning list (attribution). Limits and terms: [METHODOLOGY §12](docs/METHODOLOGY.md#12-sources-access-and-usage-limits). Nothing in the default run or in the container contacts them.
- **No service needs authorisation.** There are no API keys to obtain; the jury can verify everything offline.
- **Organizer data** (NASK corpora, gold labels, runs and exports built from them) is not in this repository and must not be published; mount it into `./data` locally.

## Team

Nikodem Nowak, Bartosz Kołaciński, Mateusz Kosowski, Jakub Rosiak.
