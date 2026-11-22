# Evaluation results

Aggregates only. Per-case results, run directories and the gold CSV contain organizer data and
stay private.

## Real corpora (NASK development data)

Both NASK corpora: 25 reports (15 backup, 10 mentor) → 24 unique cases → 17 campaigns → 4
operators. Team gold labels (`docs/DATA.md` §5), 300 case pairs, 19 same-campaign pairs under
strict labels. Measured on `main` @ 4f8dfb1 (22.11) with `scripts/evaluate.py`, every extractor
available (SigLIP2, InsightFace with the face reference DB, logo references, EasyOCR, bge-m3,
faster-whisper), RTX 5080. Total wall time 3 min 44 s, of which feature extraction 146 s.

```bash
uv run python scripts/evaluate.py data/nask_backup data/nask_mentor \
  --corpus-prefix B --corpus-prefix M --gold data/fixtures/gold_labels.csv --out runs/nask/evaluation.md
```

### Grouping (strict labels)

| Tier | Pairwise P | Pairwise R | Pairwise F1 | B-cubed P | B-cubed R | B-cubed F1 | ARI |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Campaign | 1.000 | 0.947 | 0.973 | 1.000 | 0.960 | 0.980 | 0.971 |
| Operator | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |

No false merge. The one missed campaign pair is the disputed campaign D (see DATA.md): under
lenient labels, which split D, campaign and operator scores are all 1.000.

### Open-set assignment (strict labels)

| Split | Known | New | Accuracy | FAR | FRR | Review rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Held-out variant of a known campaign | 5 | 0 | 100.0% | — | 0.0% | 0.0% |
| Leave one campaign out (LOCO) | 0 | 25 | 92.0% | **0.0%** | — | 8.0% |
| Cross-corpus, backup → mentor | 3 | 7 | 90.0% | **0.0%** | 0.0% | 10.0% |

Accuracy counts correct automatic decisions; the remainder went to review ("do weryfikacji"), never
to a wrong campaign. FAR is the share of truly new cases accepted as an existing campaign, FRR the
share of truly known cases called new. With 25 LOCO trials and zero false accepts, the one-sided
95% upper bound on FAR is about 11% (METHODOLOGY §11).

Under lenient labels (D split into singletons) the held-out variant stays at 100%; LOCO is 88%
with FAR 8.0% and cross-corpus 80% with FAR 12.5%. Both false accepts are the same disputed pair
from campaign D, which the strict labels treat as one campaign.

Score-only calibration on the strict splits suggests `tau_assign ≈ 0.64` (separated-score
midpoint, 5/5 known scores above it, 0 new). The decision rule uses the graph default
`tau_assign = 0.60` with margin 0.10.

### Ablation (strict labels)

Dropping any single feature family (ids, infra, asset, template, image, text, person) keeps
campaign pairwise F1 at 0.973: every campaign link is supported by more than one family.

Input-type ablation keeps only the features from one kind of artifact, with every case still in the
denominator:

| Input kept | Cases with features | Campaign P | R | F1 |
| --- | ---: | ---: | ---: | ---: |
| Saved page (HTML) only | 24 | 1.000 | 0.947 | 0.973 |
| Network log (HAR) only | 21 | 1.000 | 0.842 | 0.914 |
| Screenshot / ad creative only | 21 | 1.000 | 0.053 | 0.100 |
| Video only | 3 | 0.000 | 0.000 | 0.000 |
| All inputs | 25 | 1.000 | 0.947 | 0.973 |

No input type produces a false pair (video-only predicts no pair at all, hence P 0.000). Screenshot-only and video-only material rarely
carries enough campaign-specific evidence to group corpus cases on its own; the assignment rules
below (near-duplicate images, OCR headlines, cross-modal leads) address it for new single files.

### Sparse and degraded inputs (assignment of a single file)

Hidden-test simulation by the team on 21.11: one variant of a known campaign is submitted as a single
file against a base built without it.

| Input | Assigned to the right campaign |
| --- | ---: |
| Saved page only (MHTML) | 8 / 8 |
| Network log only (HAR) | 7 / 8 |
| Page printout only (PDF) | 7 / 8 |
| Degraded ad screenshots (cropping, compression) | 15 / 17 |

A wild test on fresh out-of-corpus scam screenshots (#69) gave 0 wrong `existing` answers on
both the development and the held-out half, and 4/5 known-campaign variants linked on the
development half.

### Runtime (same run, GPU)

| Stage | Seconds |
| --- | ---: |
| Ingestion | 1.1 |
| Feature extraction (two stages) | 146.2 |
| Clustering | 0.9 |
| Strict open-set protocol (all splits) | 21.4 |
| Strict family ablation | 6.8 |

CPU-only timings and the CPU/GPU feature equality check: [benchmark-vision.md](benchmark-vision.md).

## Fixtures (synthetic, checked in)

`uv run python scripts/evaluate.py data/fixtures/cases --corpus-prefix F --gold data/fixtures/gold_labels_fixtures.csv --out runs/demo/evaluation.md`

6 reports → 6 unique → 3 campaigns → 2 operators. Campaign and operator pairwise, B-cubed and ARI
are all 1.000. The fixtures are a smoke test for the pipeline and the protocol, not a measure of
quality: with two known cases the open-set splits are too small to mean anything (held-out
variant 50%, LOCO 50% with FAR 33.3%).

## Test on public material (not in the repository)

A wider base was built locally from 263 scam-ad screenshots published by fact-checkers (Demagog, FakeNews.pl; 155 articles, split 70/30 by story), plus the organizer cases. The images stay local and are not redistributed.

| Held-out public items (135) | Result |
|---|---|
| Linked to the right campaign (`existing`) | 46 |
| Sent to review with the right campaign | 7 |
| Wrong `existing` links | 2 (1.5%) |
| Stories absent from the base → `new` | 4 / 4 |
| Legitimate images (news portals, bank pages, photos of the same public figures) → `new` | 15 / 15 |

Most correct links come from the scam domain or ad metadata the source article gives; screenshots of the same story from different articles still link rarely (precision first). Degraded copies of base screenshots (crop 80%, scale 60%, JPEG q40, 2° rotation) were assigned to their own campaign in 80 / 80 cases, with no wrong link.
