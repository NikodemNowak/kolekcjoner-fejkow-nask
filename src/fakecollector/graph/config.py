from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from fakecollector.core.schemas import Tier


class EdgeConfig(BaseModel):
    """Configure entity frequency limits, scoring, and community detection."""

    tau: float = 0.6
    tau_assign: float = 0.6
    assign_margin: float = 0.1
    review_band: float = 0.15  # Window below tau for batch review edges.
    strong_link: float = 0.9
    review_min_campaign_evidence: float = 0.15
    review_min_score: float = 0.5
    min_campaign_evidence: float = 0.5
    campaign_key_floor: float = 0.75
    set_min_shared: int = 2
    tier_caps: dict[Tier, float] = {
        "campaign": 1.0,
        "operator": 0.4,
        "toolkit": 0.25,
        "context": 0.35,
    }
    max_df_min: int = 3
    use_default_stoplist: bool = True
    resolution: float = 1.0
    seed: int = 0
    cluster_algo: Literal["leiden", "louvain"] = "leiden"
    giant_min_size: int = 50
    giant_fraction: float = 0.05
    giant_cohesion: float = 0.5
    template_campaign_threshold: float = 0.85
    # Token-set ratio of {PERSON}-masked headline content words (text.headline_fuzzy).
    # Label-free (no gold): on the two-corpus base run, q99.5 of each headline's best match
    # among headlines of *other* unsupervised campaigns (an upload is compared with every
    # base headline, so the per-query maximum is the relevant null) = 0.636; the plain
    # pairwise q99.5 is 0.514. See scripts/calibrate_headline_fuzzy.py.
    headline_fuzzy_threshold: float = 0.64
    headline_fuzzy_min_tokens: int = 4
    # Distinct content words (no function words, placeholders or generic interface phrases,
    # core.text.informative_tokens) that two near-copy headlines must share: a token-set
    # ratio scores "kliknij tutaj i kontynuuj" or a short subset as a full match.
    headline_fuzzy_min_shared: int = 4
    # An exact headline template with fewer content words ("witaj w {PERSON}") is a generic
    # greeting or UI line, not a campaign key: it stays context evidence.
    headline_key_min_informative: int = 2
    lsh_threshold: float = 0.4
    num_perm: int = 128
    knn_k: int = 20
    text_vector_lo: float = 0.75
    text_vector_hi: float = 0.9
    # Gold landing-asset SigLIP fired on 78/4 false pairs at 0.8/0.9 and no unique true pairs.
    image_vector_lo: float = 0.9
    image_vector_hi: float = 0.97
    # Wild test: headshots and stock photos reached SigLIP 0.92-0.96 against an unrelated
    # decoy page. Below this cosine an image vector is campaign evidence only when another
    # family has campaign evidence on the same pair; alone it is context.
    image_vector_solo: float = 0.97
    # An image that is mostly one face says who is shown (person.public_figure), not which
    # campaign: its SigLIP rows are not compared (share of the largest face box in the image).
    siglip_max_face_share: float = 0.4
    # Read off the audit-03 variant cases (in-sample); must be validated on the other fold.
    crossmodal_bge: float = 0.70
    # Read off the audit-03 variant cases (in-sample); must be validated on the other fold.
    crossmodal_siglip: float = 0.90
    # Read off the audit-03 variant cases (in-sample); must be validated on the other fold.
    crossmodal_margin: float = 0.10
