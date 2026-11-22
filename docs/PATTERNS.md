# Campaign patterns in the NASK corpora

> Konkretne wartości (domeny, identyfikatory) są w prywatnym materiale na Google Drive, zgodnie z zaleceniem mentorów NASK.
>
> Placeholders: D1… landing domains, H1… other corpus hosts, PX1… Meta pixels, T1… kit tenants, L1 kit landing, IP1… non-CDN IPs, F1 favicon hash. The same label means the same value across `docs/`.

What the scam-ad operators in the two NASK corpora (25 reports: backup `B:p1…p15`, mentor `M:1…61`) reuse, and how the tool detects each pattern. Each pattern has its indicators (feature names from `core/registry.py`), example values (as placeholders), the cases where it occurs, a detection rule and known pitfalls.

**Scope and sources.** Measured on Sat 21.11 with the current extractors (`load_corpus` → A extractors; vision numbers from `docs/results-vision.md`). Gold labels are in `docs/DATA.md` §5 (campaigns A–E, operators O1–O4, toolkits). Values are indicators only, with no corpus text; concrete values are replaced by the placeholders above. How to reproduce: last section.

**Tiers.** A shared trace is evidence at one of four levels, and the tool keeps them apart on purpose:
- **campaign**: the same story told by the same team (same landing ID, same creative);
- **operator**: the same account or infrastructure behind different stories (same tenant, pixel or collector);
- **toolkit**: the same software, possibly sold to many operators (kit SDK, URL schema);
- **context**: true but too common to link anything alone (Cloudflare, a celebrity face, an imitated brand).

Only campaign-tier evidence can put two reports into one campaign (the campaign gate in `graph/fusion.py`). The other tiers are reported next to the campaign.

## Summary

| # | Pattern | Tier | Key indicators | Seen in |
|---|---|---|---|---|
| P1 | Landing-builder kit with tenant and landing IDs | campaign / operator / toolkit | `ids.kit_landing`, `ids.kit_tenant`, `kit.sdk`, `kit.path_sig`, `infra.endpoint` | 11 of 25 (A, B, C's p11, E) |
| P2 | Shared tracker accounts | operator | `ids.fb_pixel`, `infra.host_3p` (collector), `infra.endpoint` | A+B, A (cross-corpus), D |
| P3 | Tracking-parameter schema of the ad link | toolkit | `url.schema`, `ids.ad_param`, `ids.click_key` | 13 of 25 |
| P4 | Fake-portal chrome (impersonated news site) | context | `brand.impersonated`, `infra.favicon_mmh3`, `kit.path_sig` (`portal-chrome`) | A, B, D, E |
| P5 | Rotating domains, constant page | campaign | `html.dom_minhash`, `html.css_minhash`, `asset.sha256`, `ids.kit_landing` | A (5 domains), B, C, E |
| P6 | Cloaking: one URL, different pages | flag | `cloaking_suspected` | M:61 |
| P7 | Order-lander kit (supplement / "order now" pages) | toolkit | `infra.endpoint` (`fb-order.php`), `infra.host_3p` (`H2`), DOM/CSS | p9, p10, M:47 |
| P8 | Creative and face reuse | campaign (images) / context (faces) | `img.phash`, `img.pdq`, `img.siglip`, `person.public_figure`, `asset.sha256` | every multi-case campaign |
| P9 | CDN-fronted, single-host infrastructure | context / operator | `infra.server_stack`, `infra.ip`, `infra.ns` | 16 of 25 behind Cloudflare |

Not found: no HTTP redirect chain, no shared TLS certificate or SAN, no shared non-CDN IP, no shared Google tag, and no shared click key across reports (P10).

---

## P1: Landing-builder kit with tenant and landing IDs

**What it is.** A hosted landing-page builder ("aio" kit) serves the fake article from the operator's own domain. Its assets live under a path that names the builder's customer (**tenant**) and the page (**landing**): `/_cdn/production/landing-cdn/<tenant>/<landing>/…`. The page loads the builder's SDK and reports every visit and form field back to the builder's API.

**Indicators**
| Feature | Example value | Cases | Tier |
|---|---|---|---|
| `ids.kit_landing` | `L1` | B:p1, p2, p7, p15, M:1, M:2 (all of campaign A, 5 domains) | campaign |
| `ids.kit_tenant` | `T1` | A (6) + B (p3, p4) | operator |
| `ids.kit_tenant` | `T2` | B:p6, B:p12 (two singleton stories) | operator |
| `ids.kit_tenant` | T3 (short numeric) | M:48, M:61 (campaign E) | operator |
| `kit.sdk` / `kit.path_sig` | `/aio-static/sdk/main.js`, `/aio-static/sdk/main.css` | 11 cases: A, B, B:p11 (C), E | toolkit |
| `infra.endpoint` | `POST {1p}/api/v1/trigger/field/{uuid}/` (11), `POST {1p}/api/v1/agent/persist-session-record/{uuid}/{uuid}` (10) | same 11 | toolkit |

**Detection rule.** Regex `landing-cdn/(?P<tenant>[\w-]+)/(?P<landing>[0-9a-f]{8}-[0-9a-f-]{27})` over HAR request URLs, HAR response bodies, saved HTML and saved kit JS (`extractors/har_ids.py`), so it also works when a report has no HAR (B:p6, B:p12). A shared landing ID links two reports as one campaign. A shared tenant only marks the same operator. The SDK path and the endpoint signatures (first-party host masked as `{1p}`, IDs masked) describe the toolkit.

**Pitfalls.** The SDK and endpoints sit in 11 of 25 reports, so they are toolkit evidence and must never merge campaigns on their own (document-frequency cap). Tenant `T1` serves two different stories (A: an attack on a businessman; B: attacks on two journalists), which is the intended operator link, not one campaign.

## P2: Shared tracker accounts

**What it is.** The same Meta pixel or self-hosted collector receives the conversions of several landings, which shows one ad account or analytics setup behind them.

| Feature | Value | Cases | Reading |
|---|---|---|---|
| `ids.fb_pixel` | `PX1` | B:p1, p2, p7 (A) + B:p3, p4 (B) | operator O1 = A ∪ B |
| `ids.fb_pixel` | `PX2` | B:p15, M:1, M:2 | campaign A across both corpora |
| `infra.host_3p` + `infra.endpoint` | `H4 (AWS ECS collector)`, `POST …/events?cee` | B:p1, p2, p7 (A) + B:p3, p4 (B) | operator O1 (same pixel set) |
| `infra.host_3p` + `infra.endpoint` | `H1`, `GET {1p}/include/events-stat.js` | B:p5, M:3 | campaign D (disputed) / operator O4 |

**Detection rule.** Pixel IDs come from `fbq('init', …)`, `facebook.com/tr?id=…` and `connect.facebook.net/signals/config/<id>` (HTML, JS and HAR). Collectors are third-party hosts of the landing's request graph (`extractors/infra.py`) that are not on the platform stop-list (`graph/stoplist.toml`). All of these are operator tier.

**Pitfalls.** A pixel can be shared by unrelated advertisers of one agency, so it is never campaign evidence alone. `facebook.com/tr` itself is stop-listed: only the pixel ID counts.

## P3: Tracking-parameter schema of the ad link

**What it is.** The ad click lands with a fixed set of parameter names whose values change per ad or click. The *names* identify the traffic setup; the *values* are per-ad noise.

| Feature | Value | Cases |
|---|---|---|
| `url.schema` | `/?utm_campaign&utm_content&utm_id&utm_medium&utm_visit` | 13: A, B, B:p6, B:p11, B:p12, E |
| `ids.ad_param` | `utm_campaign=…`, `utm_content=…`, `utm_id=…` (same values) | only B:p1 = B:p2 (the same report twice) |

**Detection rule.** `url_schema()` keeps the path shape (UUIDs, hex and digit runs masked) and the sorted parameter names (`ingest/normalize.py`). Ad parameters (`utm_campaign`, `campaign_id`, `adset_id`, …) and click keys (`clickid`, `key`, `lpkey`, `_trk`, …) are separate features; tracking parameters are stripped from the canonical landing URL after extraction. Credential-like parameters (`access_token`, …) are redacted before storage.

**Pitfalls.** The schema above is the aio kit's default (P1), so it is toolkit evidence. Equal ad-parameter values mean the same ad, which on this data only happens for a duplicate report.

## P4: Fake-portal chrome

**What it is.** The landing dresses up as a known news portal so the story looks like journalism. The aio kit ships this as a module: assets under `…/vendor/portal-chrome/gazeta…`, a copied Gazeta.pl favicon and the title suffix "— Gazeta.pl".

| Feature | Value | Cases |
|---|---|---|
| `brand.impersonated` (title suffix, A's rules) | `gazeta_pl` | all 6 of campaign A |
| `infra.favicon_mmh3` | `F1` (the same 15 KB `.ico`, saved once as `gazeta.ico`) | 11: A, B, B:p5 (D), E |
| `kit.path_sig` | `/_cdn/production/landing-cdn/{uuid}/{uuid}/vendor/portal-chrome/gazeta…` | 8: A, B |
| `brand.impersonated` (SigLIP logo match, B) | TVN24 in M:3, App Store in M:10 | see `docs/results-vision.md` |

**Detection rule.** Title suffix after a separator (`— | : ·`), `og:site_name` and "logo" images are matched against a brand list (`extractors/brand_rules.py`), with the same slugs as B's logo matcher (`extractors/brand.py`). A page on the brand's own domain is not counted. The favicon hash is Shodan-style mmh3 of the base64 bytes.

**Pitfalls.** This is context, not linkage. The same imitation chrome appears in four campaigns, so `brand.impersonated` alone linked only wrong pairs (6 fires, 0 true positives in `docs/results-vision.md`), and the favicon's document frequency (11/25) is above every cap. Use it to describe a campaign ("impersonates Gazeta.pl"), never to link it. Brand names inside the story ("founder of InPost") are deliberately ignored.

## P5: Rotating domains, constant page

**What it is.** One campaign moves between cheap domains (`.click`, `.live`) while the page stays byte-for-byte or structurally the same. This is the main way a new variant gets linked to a known campaign.

| Campaign | Domains (defanged) | What stays constant |
|---|---|---|
| A | D1, D2, D3, D15, D16 | landing ID (P1), DOM / CSS 1.00, 15–16 identical assets per pair |
| B | D4, D5 | tenant, CSS 1.00, DOM 0.85, identical masked headline ("PILNE: … na {PERSON}…") |
| C | D6, D7 | 23 identical assets, DOM 0.95; **different** hosting stacks (P9) |
| E | D18, D19 | tenant T3, identical title, CSS 0.83 |

**Template similarity by relation** (MinHash Jaccard, both corpora, 273 page pairs; DOM = 4-grams of `depth:tag` tokens, CSS = class vocabulary):
| Relation | Pairs | DOM median (max) | CSS median (max) |
|---|---:|---|---|
| same campaign | 19 | 1.00 | 1.00 |
| same toolkit (aio), other campaign | 61 | 0.01 (0.21) | 0.00 (0.52) |
| unrelated | 193 | 0.01 (0.12) | 0.00 (0.31) |

**Detection rule.** Exact asset reuse (`asset.sha256` ≥ 512 B, IDF-weighted) and high DOM + CSS similarity are campaign evidence. A shared kit with low DOM similarity is toolkit only.

**Pitfalls.** 66 asset hashes repeat across reports, and 19 of them across *different* campaigns (fonts, kit chrome, jQuery, `fbevents.js`, up to 17 reports). Document frequency suppresses them; no file is stop-listed by hand. D's two reports share almost no template (DOM 0.02): only its tracker and a face connect them, which is why D is labelled "disputed".

## P6: Cloaking

**What it is.** The same URL shows different content to different visitors (the reviewer sees a harmless shop, the target sees the scam).

**Observed.** M:61 holds three captures of the same `D19` URL: the scam article, a shop page and a "portal" page. Their visible-text 5-shingle Jaccard is 0.00–0.16, so these really are different pages.

**Detection rule.** Page variants inside a report are kept (never deduplicated by URL). If two captures of one canonical URL have visible-text Jaccard < 0.5, the report gets `cloaking_suspected` (`ingest/casefolder.py`). The text comparison matters: one page saved by two tools never gives identical bytes, so a byte comparison would flag every re-capture.

**Pitfalls.** A capture-error page (B:p1's 502 archive) is excluded, otherwise every dead re-capture would look like cloaking.

## P7: Order-lander kit

**What it is.** A second, simpler kit for product offers ("supplement", "recipe"): an order form posting to a first-party PHP endpoint plus a third-party stats host.

| Feature | Value | Cases |
|---|---|---|
| `infra.endpoint` | `POST {1p}/fb-order.php` | B:p9, B:p10 |
| `infra.host_3p` | `H2` | B:p9, B:p10 |
| DOM / CSS | 0.36 / 0.69 between B:p10 and M:47; 0.04 / 0.02 between B:p9 and B:p10 | |

**Reading.** Gold labels these as three singleton stories with a weak common toolkit. The endpoint and the stats host say "same lander software". p10 and M:47 additionally share a page template. None of this is campaign evidence.

**Pitfalls.** `H2` and `{1p}` endpoints are registered as operator tier, which made B:p9 and B:p10 a false operator pair in the evaluation (reported on #16). Treating first-party endpoint signatures and analytics SaaS hosts as toolkit would fix it.

## P8: Creative and face reuse

**What it is.** Campaigns reuse the same hero images and the same celebrity photos across variants and across corpora, often recompressed or cropped.

**Observed** (`docs/results-vision.md`, 19 positive pairs):
- **Creatives:** perceptual hashes find almost all of them. `img.phash` fires on 23 pairs (19 true, recall 1.00); `img.pdq` on 20 pairs (18 true). SigLIP above 0.908 has precision 1.00, but only for 3 pairs.
- **Faces:** `person.public_figure` (InsightFace against the public-figure reference DB) has recall 0.84 but precision 0.64. The same celebrity appears in unrelated campaigns, e.g. B:p1 (A) and M:48 (E).
- **Flat UI mock-ups:** a fake banking-app screen appears byte-identical in B:p5 (D) and M:61 (E), and merged them until mostly flat images were excluded from perceptual hashing (#22).

**Detection rule.** Image near-duplicates are campaign evidence. Faces and brands are context: they explain a link but never create one alone. Unmatched faces are not stored.

**Pitfalls.** Stock photos and kit mock-ups are shared across campaigns. They need a document-frequency cap and the flat-graphic gate.

## P9: CDN-fronted, single-host infrastructure

**What it is.** Almost every landing hides behind Cloudflare, so IPs and ASNs say little. The few that do not are informative.

| Feature | Value | Cases |
|---|---|---|
| `infra.server_stack` | `server=cloudflare` | 16 of 25 |
| `infra.server_stack` | `server=cloudflare\|via=caddy` | B:p5, M:3 (D), M:36 |
| `infra.ip` (non-CDN) | `IP1` (B:p8), `IP2` (B:p11) | campaign C, both DigitalOcean (AS14061), different IPs |
| `infra.server_stack` | `server=nginx\|x-powered-by=php/8\|via=caddy` (B:p8) vs `server=nginx/1` (B:p11) | C runs on two different stacks |

**Detection rule.** CDN edge IPs (Cloudflare and Fastly published ranges) are stop-listed. A non-CDN IP is an operator trace. The server stack is context. Opt-in enrichment (`ALLOW_ENRICH=true`, `enrich/`) adds the NS pair (Cloudflare assigns one pair per account: an operator trace), ASN, registrar and registration month, and checks the CERT Polska warning list.

**Pitfalls.** A campaign can rotate hosting as well as domains (C), so infrastructure must never be required for a campaign link. "Absent is not dissimilar": a report without a HAR is not compared on infrastructure at all.

## P10: Looked for, not found

| Pattern | Result on the 25 reports | Consequence |
|---|---|---|
| HTTP redirect chains | none of the 24 HARs records a navigation redirect: captures begin at the landing page. The only 3xx responses are sub-resources (video CDNs, a JS CDN, Google), which `infra.redirect_hop` now ignores | hop detection (navigation 3xx, meta refresh, JS `location`) stays for the hidden set |
| Shared TLS certificate / SAN | only 1 `dns_ssl.json` and 1 HAR with `_securityDetails` in both corpora | needs opt-in crt.sh enrichment |
| Shared non-CDN IP | none (C uses two different IPs) | IP is operator evidence only |
| Shared Google tag (`G-`, `AW-`, `GTM-`) | none | kept as a feature for the hidden set |
| Shared click key value | none | click keys are per click; the schema (P3) is what repeats |

## Data-quality patterns the tool handles

- **Duplicate report:** B:p2's files are a subset of B:p1's → `duplicate_of` (kept as a report: "25 reports → 24 unique").
- **Dead capture:** B:p1 contains a 502 archive next to a working save → `capture_error`; the error page gives no template or text features.
- **Misplaced HAR:** `D17.har` was filed in M:2 but captures M:3's page. It moves to M:3 (`har_moved_out` / `har_moved_in`); before this fix it merged campaign D into A.
- **Video-only report:** M:5 → `video_only`; video keyframes (and optional ASR) provide its features.
- **Odd file names:** mojibake and non-UTF-8 names are kept for reading but escaped in ids, metadata and locators.

## Reproduce

```bash
uv run python scripts/evaluate.py data/nask_backup data/nask_mentor \
    --corpus-prefix B --corpus-prefix M --gold data/fixtures/gold_labels.csv --out docs/results.md
uv run python scripts/b_eval.py      # vision table in docs/results-vision.md (B)
```

The shared-value tables above come from running the A extractors (`IdsExtractor`, `AssetExtractor`, `RequestGraphExtractor`, `TemplateExtractor`, `InfraMetaExtractor`, `BrandRulesExtractor`) over `load_corpus(...)` for both corpora and counting values found in at least two reports (CPU, base install, about 2 minutes).
