# Data guide

> Konkretne wartości (domeny, identyfikatory) są w prywatnym materiale na Google Drive, zgodnie z zaleceniem mentorów NASK.
>
> Placeholders: D1… landing domains, H1… other corpus hosts, PX1… Meta pixels, T1… kit tenants, L1 kit landing, IP1… non-CDN IPs, F1 favicon hash. The same label means the same value across `docs/`.

Two real corpora from NASK, 25 **cases** in total. Everything below marked *measured* was computed from the local files on Sat 21.11 (HAR/HTML parsing only; nothing was fetched or executed).

## 1. Datasets and how to get them

| Corpus | Local path (git-ignored) | Size | How to obtain |
|---|---|---|---|
| **NASK backup** (teaser `___BACKUP.zip`) | `data/nask_backup/p1..p15/` | 15 cases, 136 MB | provided by the organizers (private access instructions). Symlink `data/nask_backup` → `<decrypted>/BACKUP`. |
| **NASK mentor data** (`DANE.zip`, handed over Sat) | `data/nask_mentor/{1,2,3,5,10,14,36,47,48,61}/` | 10 cases, 362 files, 557 MB | Provided by the organizers as `DANE.zip`; verify `sha256sum` against the value in the private Google Drive material; unzip **outside the repo**; `ln -s <unzipped>/do_udostępnienia data/nask_mentor`. |
| Purino/scam-ads-detection-dataset (HF, MIT) | `data/purino/` | 3.7k ad images | Optional **[S]**, only for the scale benchmark (Task 8). ScamWeb is dropped. |

`data/` is git-ignored except `data/README.md` and `data/fixtures/`. Fixtures are **synthetic** (built by `scripts/make_fixtures.py`).

**Data rules (task v2 §8):** organizer material is for this challenge only and **must not be distributed publicly**. The repo stays private; never copy corpus files, screenshots, saved HTML, text excerpts or caches derived from them into git, PRs, public slides or chat tools. Extra public data is allowed if its source is named (README credits table).

**Hidden test set (task v2 §6):** the jury will run the tool on material we have not seen: new variants of known campaigns plus other campaigns, possibly as a bare URL, a single screenshot, a HAR, a media file, with dead pages or missing files. Everything in this guide is a description of the *sample*; no code may depend on a folder name, a file name or a specific ID value from it.

## 2. Safety rules (real, partly live scam material)
- **Never open or fetch any URL found in the data** (browser, `curl`, `requests`, link previews). Enrichment is passive only and only for the registrable domain (DNS, RDAP, crt.sh), behind `ALLOW_ENRICH=true`.
- **Never execute corpus code.** `*.pobrane` / `*.pobierz` / `*.js` / `js@latest` files are saved JavaScript (Polish Chrome's `.download` suffix). Read them as bytes (hash) or text (regex) only.
- Parse HTML with `lxml` / `BeautifulSoup`; do not render it in a networked browser. Do not open `.html` / `.mhtml` by double-click.
- Treat every file as untrusted input: pass paths as arguments, catch parser errors per artifact, cap sizes (`MAX_ARTIFACT_MB`).
- Reports and screenshots for the pitch show **defanged** domains (`example[.]com`).
- Faces: match only against the public-figure reference DB; do not store embeddings of unmatched faces.
- **No corpus values in git** (NASK mentors' rule): domains, IPs, pixel/tag/kit IDs, hashes, phone numbers and page titles from the corpora go to the private Google Drive material; tests use synthetic values (`example-lander.com`, `203.0.113.x`, pixel `1111222233334444`). Before pushing docs or tests, run `uv run python scripts/check_no_corpus_values.py --features runs/<run>/features.parquet` (exit 1 lists the files; add `--show-values` locally). Without a run it skips, so CI cannot enforce it.

## 3. The case-folder abstraction

**A case = one top-level folder = one report of an ad and what it led to.** The case is the node that gets clustered. `ingest/casefolder.py` walks a case recursively (`Path.rglob("*")`, hidden files included) and emits typed `Artifact`s with a `role`; extractors turn artifacts into `Feature`s and graph entities. A case may contain several **page variants** of the same URL (cloaking), nested sub-folders, or just one video.

| File pattern (measured occurrences) | Artifact `kind` / `role` | Features and entities derived |
|---|---|---|
| `*.har`, `network.har`, `page.har`, **`.har`** (hidden, case 61) — 24 HARs, 3 creators (WebInspector, Playwright, page-capture) | `har` / `network` | landing URL + query-parameter schema, ad/click IDs, every contacted host, `serverIPAddress`, response headers (`server`, `via`, `x-powered-by`), first-party path signatures, POST endpoints, pixel IDs, response-body sha256, capture time |
| `<title>.html` / `.htm` (browser "save page"), `dom.html`, `html/rendered.html` — 27 pages | `html` / `landing_page` | `saved from url=` comment (landing URL when no HAR exists: p6, p12, p14, M3), title, visible text, DOM tag-path shingles, CSS class set, tracker IDs, form actions, outlink domains, kit markers |
| `<title>_files/*`, `resources/{image,script,stylesheet,media}/*` — 461 distinct files ≥ 512 B | `asset` / `landing_asset` (child of the page) | sha256 (**strongest signal**), type, favicon mmh3; images also go to the vision extractors |
| `Zrzut ekranu*.png`, `screenshots/*.png`, `screenshot.png`, `IMG_*.PNG`, `reklama_*.png`, `.jpg/.webp` at case level — 38 | `image` / `screenshot` (ad creative or landing view) | pHash/PDQ, SigLIP2, OCR text (advertiser name, headline, domain typed in the ad), faces |
| `*.mp4`, `*.MP4`, `*.ts` + `*.m3u8` — 3 videos (166–249 s) + 1 HLS stream | `video` / `ad_video` or `screen_recording` | keyframes → image + face features; audio → faster-whisper transcript → text features |
| `*.info.json` (yt-dlp, extractor `facebook:ads`, case 5) | `json` / `ad_library_meta` | Ad Library ID (`playlist_id`), advertiser name + page ID (`playlist_uploader`, `playlist_uploader_id`), `webpage_url` |
| `archive_info.json`, `metadata.json`, `manifest.json` | `json` / `capture_meta` | canonical landing URL, capture timestamp, user agent, title |
| `dns_ssl.json` (**only 1 in the whole corpus**, p1) | `json` / `dns_tls` | IPs, cert issuer, serial, SAN list, validity dates |
| bare URL, product name or other hint (no file) | `url` / `text` | registrable domain, URL schema, click and ad IDs, text features; [S] public DNS / RDAP / crt.sh metadata |
| `page.mhtml`, `page.pdf`, `page_text.txt`, `storage/*.json`, `sha256.json`, `*.zip` | `mhtml` / `pdf` / `text` / ignored | fallback text source; `sha256.json` verifies the archive; the `.zip` duplicates its folder and is skipped |

Known quirks (each has a test in Task 1): mojibake file names in p3, p4, p8, p11, p13 (use the HTML `<title>`, never the file name); `.htm` in p7; `D17.har` sits in case **2** but belongs to the page saved in case **3** (attach a HAR to a page by landing host, and let cross-case entity links do the rest); p1 was captured twice (502 error archive + working browser save); p1 ≡ p2 byte-identical; `video_deleted.txt` marker in p10; values `[REDACTED]` in case 14.

## 4. What the data shows (measured)

1. **No redirect chains.** 0 of 24 HARs contain an HTTP redirect on the landing chain (captures start at the landing page). The usable "where does it lead" signal is the **request graph**: which third-party hosts, collectors and endpoints the landing talks to, and the click-tracker parameters left in the landing URL (`clickid`, `key`, `lpkey`, `_trk=bf1` ↔ host `H3`).
2. **IP/ASN is almost useless alone.** 18 of 20 landing hosts sit behind Cloudflare; the anycast IPs `188.114.96.11` / `.97.11` are shared by 9 unrelated landings. The only two non-CDN hosts (p8 `IP1`, p11 `IP2`, both DigitalOcean) belong to the same campaign C. → stop-list CDNs, IDF-weight the rest.
3. **A shared landing-builder kit exposes tenant and landing IDs.** 13 of 25 cases load `/aio-static/sdk/main.js` (byte-identical 870 kB file in 11) and call `/api/v1/trigger/field/{visit}/` and `/api/v1/agent/persist-session-record/{visit}/{uuid}`; assets come from `/_cdn/production/landing-cdn/<tenant>/<landing>/…`. Tenant `T1` serves campaigns A **and** B; landing `L1` is campaign A on five different domains; tenant `T2` serves p6 and p12; tenant T3 (a short numeric ID) serves M48 and M61. The kit itself is too common to link campaigns (document frequency 13/25) but is intelligence in its own right.
4. **Tracker IDs link operators across campaigns.** Meta pixel `PX1`: p1, p2, p3, p4, p7. Pixel `PX2`: p15, M1, M2. Collector host `H4 (AWS ECS collector)/events?cee=no`: p1, p2, p3, p4, p7. Host `H1` + identical `/include/events-stat.js`: p5 and M3. `H2`: p9, p10.
5. **Exact asset reuse beats perceptual similarity.** 57 asset hashes repeat across cases; 194 cross-case image pairs are sha256-identical versus only 12 more found by pHash ≤ 8. Case-level screenshots are weak: pHash links only p1 = p2 (same file); campaign A screenshots differ by ≥ 16 bits. `fbevents.js` (17 cases) and jQuery builds must be suppressed by document frequency.
6. **Template similarity separates tiers.** DOM 4-gram Jaccard / CSS-class Jaccard / text 5-shingle Jaccard: inside A 1.00 / 1.00 / ≥ 0.96; p8–p11 0.93 / 0.26 / 0.84; p3–p4 0.85 / 1.00 / 0.56; A vs B 0.19 / 0.51 / 0.00 (same fake-Gazeta chrome, different story); M48–M61 0.38 / 0.76 / 0.10; p10–M47 0.36 / 0.63 / 0.00 (same supplement lander kit). Median over all pairs 0.02 / 0.00.
7. **Cloaking is in the data.** Case 61 holds three captures of the *same* `D19` URL: the scam article (`strona_1`), a shop page (`strona_2`) and a "portal" page (`strona_3`). Never deduplicate page content by URL; keep variants and flag `cloaking_suspected`.
8. **Ad screenshots carry the advertiser.** The ad screenshot in case 61 reads "Sponsorowane · <advertiser>" where the advertiser name equals the landing domain D19; case 3's ad shows an advertiser page with two public figures. OCR → `ad.advertiser`, `ocr.domain`.

## 5. Gold labels (combined, 25 cases)

Derived by hand from the measurements above; not an official ground truth. File: `data/fixtures/gold_labels.csv` (`case_id,campaign,operator,toolkit,note`; labels only, no corpus content). Case IDs are `B:p7`, `M:48`.

| Campaign | Cases | Landing domains | Verified by |
|---|---|---|---|
| **A** fake Gazeta.pl article about an "assassination attempt" on a business founder | B:p1, B:p2, B:p7, B:p15, M:1, M:2 | D1, D2, D3, D15, D16 | same kit landing ID, 15–16 identical assets per pair, DOM 1.00 |
| **B** "PILNE: … na {PERSON}" (attack on a journalist, two journalists) | B:p3, B:p4 | D4, D5 | same tenant, CSS 1.00, 7 identical assets, title equal after masking the person |
| **C** one "investment" article, identical title | B:p8, B:p11 | D6, D7 | 23 identical assets, text 0.84, **different** serving stack |
| **D** fake interview with a well-known TV journalist | B:p5, M:3 | D8, D17 | same tracker host and JS, same URL schema, same person; different article text (**disputed**: report strict and lenient) |
| **E** fake "arrested after the broadcast" story, identical title | M:48, M:61 | D18, D19 | same tenant, identical title, 8 identical assets |
| singletons | B:p6, B:p9, B:p10, B:p12, B:p13, B:p14, M:5, M:10, M:14, M:36, M:47 | D9, D10, D11, D12, D13, D14, –, D20, D21, D22, D23 | – |

**Operator labels (second tier):** O1 = A ∪ B (tenant `T1`, shared pixel and collector); O2 = {B:p6, B:p12} (tenant `T2`); O3 = E; O4 = D. **Toolkit labels (third tier):** `aio-kit` = A, B, E, B:p6, B:p11, B:p12; `order-lander` = B:p9, B:p10, M:47 (weak: `fb-order.php` / `order.php`, 8-character path, `H2`).

Strict campaign labels give 19 positive pairs out of 300. The same labels drive the **open-set protocol** in Task 8 (hold-out variant, leave-one-campaign-out, backup → mentor), which simulates the hidden test set. The must-pass behaviours: A is recovered across both corpora; A and B stay **separate campaigns** but share an operator; C is recovered although its two members run on different stacks; M:5 (video only) and M:10 stay singletons.

## 6. Pointers per workstream

- **A (ingest, infra):** start from `ingest/casefolder.py` and the quirks list in §3. HAR creators differ: only the Playwright HAR has `_securityDetails`; WebInspector HARs keep bodies in `response.content.text` (base64 when `encoding` is set). Landing URL priority: `archive_info.json` / `manifest.json` → first HAR document entry with status 200 → `saved from url=`. Kit IDs come from a regex over HAR URLs **and** saved HTML (p6, p12 have no HAR).
- **B (vision, video):** inputs are case-level screenshots (38), content images inside `_files/` / `resources/image/` (≈ 280 ≥ 120 px) and video keyframes. Skip images < 120 px and assets with document frequency > 30 %. Reference faces needed for this corpus: Brzoska, Morawiecki, Stanowski, Sekielski, Olejnik, Glapiński. Videos: `5/*.mp4` (198 s), `47/*.mp4` (166 s), `14/*.MP4` (249 s, HEVC 1170×2532, 339 MB: decode at 1 fps, downscaled).
- **C (text, fusion, eval):** texts come from page visible text (0.7–34 k characters), OCR and ASR. The numbers in §4.6 are the calibration anchors; `gold_labels.csv` is the evaluation target; the A-versus-B separation is the regression test for the campaign/operator split. Incomplete inputs are already in the sample: B:p1's archive is a 502 page, B:p6 / B:p12 / B:p14 / M:3 have no HAR, M:5 has only a video, M:61 has an ad screenshot plus three page variants.
- **D (pipeline, app, exports):** the demo path is `fakecollector run data/nask_mentor data/nask_backup --out runs/demo`; the hidden-test path is `fakecollector assign <new> --against runs/demo`, and both must work on CPU. The feature cache lives outside git. `export --format dataset` is the enriched dataset the organizer asked for (handed over outside git). Show case 61's cloaking variants and the A-across-two-corpora story in the report.

## 7. Sharing the feature cache

Model features are cached per `(artifact sha256, extractor, version)` under `~/.cache/fakecollector/` (or `FEATURE_CACHE`), so one teammate's GPU run can save everyone else the model work. The cache contains **organizer-derived data** (OCR and ASR text, face matches, keyframes cut from the videos): share it **only privately inside the team** (direct file transfer, team drive with access limited to us), **never in git, PRs, issues or public links**. `data/` is git-ignored, so the archive stays out of commits as long as it lives there.

1. Producer (after a full run): `PYTHONPATH=src python scripts/export_feature_cache.py` → `data/exports/feature-cache-<date>.tar.gz` plus `<archive>.manifest.json` (extractor names, cache versions, entry counts, size, sha256). Only entries for artifacts of the two corpora (and their keyframes) are packed; `--all` packs the whole cache. Both corpora: ≈ 4 MB.
2. Teammate: put both files in `data/exports/`, then `PYTHONPATH=src python scripts/import_feature_cache.py data/exports/feature-cache-<date>.tar.gz`. It verifies the sha256 against the manifest, extracts only `features/` and `keyframes/` entries (links and paths outside them are rejected) and keeps files that already exist.
3. Confirm the hits: `PYTHONPATH=src python scripts/b_extract_all.py`. A warm run prints `computed 0` for every stage (all `cached`) and finishes in about 2 s; any non-zero `computed` means a different extractor version, reference DB or model setting than the producer's (the cache version string in the manifest shows which). ASR entries are keyed by the Whisper model (`turbo` on GPU, `small` on CPU), so a CPU teammate who forces ASR recomputes it.
