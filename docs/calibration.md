# Similarity anchor calibration

Cases: 6. Pseudo-count: 200. Perturbation seed: 0.

| Feature | Pairs | Prior lo / hi | Null n / max / q99 / q99.5 | Synthetic n / p10 | Proposed lo / hi | Verdict |
|---|---:|---:|---:|---:|---:|---|
| `asset.sha256` | 3 | 0.1500 / 0.6000 | 0 / — / — / — | 2 / 1.0000 | 0.1500 / 0.6040 | more conservative |
| `text.minhash` | 10 | 0.3000 / 0.7000 | 0 / — / — / — | 6 / 0.0000 | 0.3000 / 0.6796 | more conservative |
| `text.bge` | 0 | 0.7500 / 0.9000 | 0 / — / — / — | 0 / not measured | 0.7500 / 0.9000 | more conservative |
| `html.dom_minhash` | 10 | 0.5000 / 0.9000 | 0 / — / — / — | 5 / 0.5234 | 0.5000 / 0.8908 | more conservative |
| `html.css_minhash` | 10 | 0.5000 / 0.9000 | 0 / — / — / — | 6 / 0.0898 | 0.5000 / 0.8764 | more conservative |
| `img.phash` | 0 | 0.8600 / 0.9700 | 0 / — / — / — | 0 / not measured | 0.8600 / 0.9700 | more conservative |
| `img.pdq` | 0 | 0.8500 / 0.9500 | 0 / — / — / — | 0 / not measured | 0.8500 / 0.9500 | more conservative |
| `img.siglip` | 0 | 0.9000 / 0.9700 | 0 / — / — / — | 0 / not measured | 0.9000 / 0.9700 | more conservative |

Each feature is scored on all comparable case pairs before blocking and fusion. A pair enters its null set when it shares no active campaign-tier key and no other family produces graph evidence at the current priors. Asset scores use the graph's IDF-weighted containment over active hashes before the minimum-shared-files rule. The null set is a proxy for unrelated pairs and can include real matches.

Synthetic positives compare originals to one seeded variant per distinct text source, HTML artifact or eligible case asset set. Text variants drop 10–30% of tokens and swap numbers and likely names. Local HTML from the artifact table is parsed offline for block removal and CSS class renaming. Asset variants lose 30–70% of unique files (rounded to whole files). A retained subset with an active hash has containment 1. BGE has no synthetic embedding measurement.

The measured lower anchor is the greater of the prior and null q99.5. The measured upper anchor is synthetic p10. Each is averaged with its prior using its own sample count `n` and prior pseudo-count `n0`, as `(n * measured + n0 * prior) / (n + n0)`. Missing measurements retain their priors. The verdict uses the lower anchor alone. The scoring interval requires an upper anchor greater than its lower anchor.

## Image robustness input

Pass `--robustness` a JSON object keyed by `phash/regions`, `pdq/regions`, and `siglip/regions`. Each available mode has `n` and `p10` from the pooled original-pair scores across the `scripts/b_robustness.py` transforms, excluding the flip control. That script currently writes Markdown. Export the count and percentile from the original-pair scores it uses to build the table, before display rounding. Hash scores are negative Hamming distances, converted to `1 + p10 / bits`. SigLIP uses cosine.

```json
{
  "phash/regions": {"n": 1200, "p10": -16},
  "siglip/regions": {"n": 1200, "p10": 0.82}
}
```

## Reproducing the checked-in report

The checked-in numbers come from the synthetic fixture run. Regenerate them on the real corpora on the GPU box and keep those outputs with that run.

```sh
uv run fakecollector demo --fixtures --out runs/calibration-fixtures
uv run python scripts/calibrate.py runs/calibration-fixtures
```
