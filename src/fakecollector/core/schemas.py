"""Shared data contract (Task 0): every module exchanges these models, never bare dicts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

ArtifactKind = Literal[
    "har", "html", "asset", "image", "video", "json", "mhtml", "pdf", "text", "url"
]
Role = Literal[
    "network",
    "landing_page",
    "landing_asset",
    "screenshot",
    "ad_creative",
    "ad_video",
    "screen_recording",
    "ad_library_meta",
    "capture_meta",
    "dns_tls",
    "source_meta",
    "other",
]
Family = Literal["ids", "infra", "asset", "template", "image", "text", "person", "meta"]
Tier = Literal["campaign", "operator", "toolkit", "context"]


class Case(BaseModel):
    """One report (one folder or one upload); the unit that gets clustered."""

    id: str  # "<corpus>:<folder>", e.g. "M:61"; uploads: "U:<sha8>"
    corpus: str
    path: Path | None
    landing_urls: list[str] = []  # canonical; tracking parameters are kept as features
    captured_at: datetime | None = None
    duplicate_of: str | None = None  # byte-identical report of an earlier case
    flags: list[str] = []  # "cloaking_suspected", "capture_error", "video_only", ...


class Artifact(BaseModel):
    """One typed file (or URL) inside a case."""

    id: str  # sha256 of the bytes, first 16 hex
    case_id: str
    kind: ArtifactKind
    role: Role
    path: Path
    page: str | None = None  # capture variant inside the case ("strona_1"); None = default
    parent_id: str | None = None  # asset -> page, keyframe -> video
    size: int
    meta: dict[str, str] = {}


class Feature(BaseModel):
    """One observed signal with provenance back to its artifact."""

    case_id: str
    artifact_id: str
    name: str  # registry key, e.g. "ids.fb_pixel", "asset.sha256", "img.siglip"
    value: str  # hashable key ("" for vector-only features)
    vector: list[float] | None = None
    confidence: float = 1.0
    locator: str = ""  # "entry[12].request.url", "img#hero", "t=14.0s bbox=..."


class Entity(BaseModel):
    """A node of the entity graph, built from key features."""

    id: str  # "<type>:<value>", e.g. "KitLanding:00000000-..."
    type: str
    value: str
    tier: Tier
    df: int  # number of cases that have it
    stop: bool = False  # stop-listed or df above the cap -> never evidence


class Evidence(BaseModel):
    """One human-readable reason why two cases are linked."""

    family: Family
    tier: Tier
    kind: str  # Feature.name
    value: str  # shared key or similarity, e.g. "1111222233334444" / "J 0.84"
    detail: str  # Polish, human readable
    weight: float  # this signal's probability contribution p_k, 0..1
    artifacts: list[str] = []  # artifact ids (+ locators) on both sides


class Edge(BaseModel):
    """A case-to-case link with per-family scores and its evidence."""

    src: str  # case ids, src < dst
    dst: str
    score: float  # fused probability "same campaign", 0..1
    operator_link: bool  # a rare operator-tier entity is shared
    signals: dict[Family, float]  # per-family p_f (ablation, UI bars, model input)
    comparable: list[Family]  # families both sides could provide; the rest are "no data", not 0
    evidence: list[Evidence]


class Assignment(BaseModel):
    """The answer for one new case against an existing run."""

    case_id: str
    decision: Literal["existing", "new", "review"]
    campaign_id: str | None  # best campaign when "existing" / "review"
    score: float  # campaign-level score
    margin: float  # gap to the runner-up campaign
    operator_id: str | None = None  # may be set when decision == "new" (known operator)
    toolkits: list[str] = []
    duplicate_of: str | None = None
    comparable: list[Family]
    evidence: list[Evidence]
    flags: list[str] = []  # "insufficient_data": only a URL on a domain unseen in the base


class Trait(BaseModel):
    """One line of a campaign's common-traits profile."""

    entity_type: str
    value: str
    tier: Tier
    coverage: float  # share of members that have it
    lift: float  # coverage / corpus frequency
    kind: Literal["constant", "rotating"]
    why: str  # Polish: why this trait matters to an analyst


class Campaign(BaseModel):
    """A group of cases judged to be the same campaign."""

    id: str  # stable: hash of the smallest member id
    operator_id: str | None
    toolkits: list[str] = []
    case_ids: list[str]
    label: str  # auto: person + narrative template / top keywords
    traits: list[Trait]
    cohesion: float  # mean internal edge score; low -> "needs review"
    flags: list[str] = []
