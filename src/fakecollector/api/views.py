"""Read-only view models for the web UI, built from a persisted run.

Everything user-facing is made readable here: file names instead of hashes, display names
instead of slugs, defanged domains, Polish labels. The UI never sees raw SHA-256 walls.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from functools import cached_property
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, get_args
from urllib.parse import urlsplit

from PIL import Image, ImageStat
from pydantic import BaseModel

from fakecollector.api import pl
from fakecollector.app.display import display_description, display_value
from fakecollector.app.links import neighbour_rows
from fakecollector.app.pl import PERSON_DISPLAY_NAMES
from fakecollector.core.registry import FEATURES
from fakecollector.core.schemas import (
    Artifact,
    Campaign,
    Case,
    Edge,
    Entity,
    Evidence,
    Family,
    Feature,
    Trait,
)
from fakecollector.graph.analyze import Analysis
from fakecollector.graph.entities import entity_type_for
from fakecollector.store import RunStore

if TYPE_CHECKING:
    from fakecollector.api.found import CaseTraces

logger = logging.getLogger(__name__)
_HAR_ENTRY = re.compile(r"entry\[(\d+)\]")
FAMILIES: tuple[Family, ...] = get_args(Family)
_HEX = re.compile(r"\b[0-9a-f]{24,}\b")
_DOMAIN_TYPES = {
    "Domain",
    "Host",
    "DependencyHost",
    "OutlinkDomain",
    "OcrDomain",
    "CertSan",
    "ShortLink",
}
_HIDDEN_FEATURES = {"img.phash", "img.pdq", "text.minhash", "text.bge", "img.siglip", "text.lang"}
_GENERIC_TOOLKIT_TYPES = {"DependencyHost"}
_NO_CHIP = {"Narrative", "ServerStack", "Topic", "DependencyHost", "PathSignature", "UrlSchema"}
_CHIPS = {
    "KitLanding": "ta sama strona w kreatorze",
    "KitTenant": "to samo konto w kreatorze",
    "Tracker": "ten sam piksel śledzący",
    "Endpoint": "ten sam adres zbierania danych",
    "Host": "ten sam serwer",
    "Toolkit": "ten sam program do stron",
    "AdParam": "wspólny parametr reklamy",
    "ClickKey": "wspólny klucz kliknięć",
    "Favicon": "ta sama ikona strony",
    "IP": "wspólny adres IP",
    "AdLibraryId": "ta sama reklama Meta",
    "AdvertiserPage": "ta sama strona reklamodawcy",
}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
# Text of a capture that shows an error page instead of the ad or the landing page.
_ERROR_PAGE = re.compile(
    r"bad gateway|error code:? ?[45]\d\d|\b5\d\d: |web server is down|gateway time-?out"
    r"|service (temporarily )?unavailable|cloudflare ray id|origin is unreachable|host error"
    r"|404 not found|page not found|403 forbidden|access denied|site can.t be reached",
    re.IGNORECASE,
)
_SIMILARITY = re.compile(r"(?:J|cos)\s+([01](?:\.\d+)?)")
_SENTENCE = re.compile(r"(?<=[.!?…])\s+|\s{2,}|\n+")
_STATUS = re.compile(r"\b([45]\d\d)\b")
_SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
# Face reference DB: attribution in the repo, photos fetched by scripts/fetch_face_refs.py.
FACE_REFS_CSV = Path(os.environ.get("FACE_REFS_CSV", "refs/faces.csv"))
FACE_REFS_DIR = Path(os.environ.get("FACE_REFS_DIR", "data/faces/refs"))
# Cosine similarity a face must reach to count as recognised (extractors.face.FaceConfig).
FACE_THRESHOLD = float(os.environ.get("FACE_THRESHOLD", "0.40"))
_BBOX = re.compile(r"bbox=(-?\d+,-?\d+,\d+,\d+)")
_AD_ROLES = {"ad_creative", "ad_video", "screen_recording", "ad_library_meta"}
_RECOGNISED_TYPES = {"Person", "Brand", "BrandLogo"}
# Paths, endpoints and hosts say little to a newcomer: the matrix shows them only on demand.
_TECHNICAL_TYPES = {
    "PathSignature",
    "Toolkit",
    "UrlSchema",
    "Endpoint",
    "Host",
    "DependencyHost",
    "RedirectHop",
    "CertSan",
    "Favicon",
}
_MAX_PAIRS = 40  # strongest pairs sent to the page; a 60-report campaign has 1770
_BLANK_STDDEV = 3.0
# PDQ Hamming distance (of 256): the same creative re-saved vs clearly another picture.
_PDQ_SAME = 40
_PDQ_DIFFERENT = 80
_LONG_TEXT = {"text.raw", "text.asr"}
_OCR_TEXT = {"text.ocr", "ocr.headline", "text.headline_tpl"}
_TEXT_LIMIT = 900


def defang(value: str) -> str:
    """Make a domain non-clickable: `example[.]com`."""
    host, sep, rest = value.partition("/")
    return host.replace(".", "[.]") + sep + rest


def short(value: str, limit: int = 56) -> str:
    """Shorten long values in the middle, keeping both ends readable."""
    if len(value) <= limit:
        return value
    keep = (limit - 1) // 2
    return value[:keep] + "…" + value[-keep:]


def plural_word(n: int, forms: tuple[str, str, str]) -> str:
    """Pick the Polish noun form for a count: (1, 2-4, 5+), e.g. zgłoszenie/zgłoszenia/zgłoszeń."""
    one, few, many = forms
    if n == 1:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many


def plural(n: int, forms: tuple[str, str, str]) -> str:
    """Return a Polish count label, e.g. "5 wspólnych plików"."""
    return f"{n} {plural_word(n, forms)}"


def _similarity(value: str) -> float | None:
    """Similarity 0..1 from an evidence value such as "J 0.91" or "cos 0.84"."""
    match = _SIMILARITY.fullmatch(value.strip())
    return float(match.group(1)) if match else None


def face_ref_file(slug: str) -> tuple[Path, dict[str, str]] | None:
    """The first downloaded reference photo of a person and its row of `refs/faces.csv`."""
    if not _SLUG.fullmatch(slug) or not FACE_REFS_CSV.is_file():
        return None
    with FACE_REFS_CSV.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("person_slug") != slug:
                continue
            # Same naming as scripts/fetch_face_refs.py: sha256 of the source URL, 8 hex.
            key = hashlib.sha256(row["source_url"].encode()).hexdigest()[:8]
            path = FACE_REFS_DIR / slug / f"{key}.jpg"
            if path.is_file():
                return path, row
    return None


def load_face_refs() -> dict[str, FaceRef]:
    """Reference photo (with author and licence) per person slug, where one is on disk."""
    refs: dict[str, FaceRef] = {}
    if not FACE_REFS_CSV.is_file():
        return refs
    with FACE_REFS_CSV.open(encoding="utf-8", newline="") as handle:
        slugs = list(dict.fromkeys(row.get("person_slug", "") for row in csv.DictReader(handle)))
    for slug in slugs:
        found = face_ref_file(slug)
        if found:
            _, row = found
            refs[slug] = FaceRef(
                url=f"/api/faces/{slug}/ref",
                author=row.get("author", ""),
                license=row.get("license", ""),
                source_url=row.get("source_url", ""),
            )
    return refs


def _norm(text: str) -> str:
    """Case- and whitespace-insensitive form of a sentence, for comparing page texts."""
    return " ".join(text.lower().split())


def _prose(sentence: str) -> bool:
    """A real sentence rather than a menu, a list of links or a form."""
    words = sentence.split()
    letters = [c for c in sentence if c.isalpha()]
    if len(words) < 9 or not letters:
        return False
    lower = sum(1 for c in letters if c.islower()) / len(letters)
    return lower > 0.85 and sentence[-1] in ".!?…"


def _join(parts: list[str]) -> str:
    """Join phrases the Polish way: "a, b i c"."""
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " i " + parts[-1]


def corpus_case(case_id: str) -> tuple[str, str]:
    """Split a case id into a readable corpus name and folder name."""
    corpus, _, folder = case_id.partition(":")
    return pl.CORPUS_NAMES.get(corpus, corpus), folder or case_id


def case_title(case_id: str) -> str:
    """Readable case name, e.g. "Kopia NASK · p12"."""
    corpus, folder = corpus_case(case_id)
    match = re.fullmatch(r"(demagog|fakenews)-([0-9a-f]{6,})(?:-\d+)?", folder, re.IGNORECASE)
    if match:
        folder = f"{match.group(1).capitalize()} {match.group(2)}"
    return f"{corpus} · {folder}"


# ---------------------------------------------------------------- response models


class Ref(BaseModel):
    """A link target with a readable label."""

    id: str
    label: str


class Thumb(BaseModel):
    """A thumbnail of a case image."""

    case_id: str
    artifact_id: str
    url: str
    name: str
    kind: str = "screenshot"
    kind_label: str = ""
    issue: str | None = None


class Value(BaseModel):
    """A readable value and, when shortened or derived, the raw value for a tooltip."""

    text: str
    raw: str | None = None
    mono: bool = False


class TraitRow(BaseModel):
    """One row of a readable common-traits profile (constant traits grouped by type)."""

    entity_type: str
    type_label: str
    family: str
    family_label: str
    tier: str
    tier_label: str
    kind: str
    headline: str
    values: list[Value]
    coverage: float
    lift: float
    why: str


class EvidenceKind(BaseModel):
    """Evidence of one feature kind inside a campaign, aggregated over member pairs."""

    kind: str
    label: str
    tier: str
    tier_label: str
    pairs: int
    strength: float
    values: list[Value]


class FamilyEvidence(BaseModel):
    """All evidence of one family inside a campaign."""

    family: str
    label: str
    pairs: int
    total_pairs: int
    mean: float
    kinds: list[EvidenceKind]


class GroupLink(BaseModel):
    """An operator or toolkit link to other campaigns, with the shared traces."""

    kind: str
    id: str
    label: str
    campaigns: list[Ref]
    traces: list[Value]


class Member(BaseModel):
    """One case in a campaign list."""

    id: str
    title: str
    corpus: str
    domain: str | None
    duplicate_of: str | None
    flags: list[str]
    thumb: Thumb | None


class CampaignSummary(BaseModel):
    """A campaign card on the overview page."""

    id: str
    label: str
    size: int
    operator: Ref | None
    operator_index: int | None
    toolkits: list[Ref]
    chips: list[str]
    rotating: list[str]
    persons: list[str]
    cohesion: float
    thumbs: list[Thumb]
    flags: list[str]
    domains: list[str] = []
    plain: str = ""


class PairLink(BaseModel):
    """Why two members of a campaign are linked: fused score and the strongest reasons."""

    a: Ref
    b: Ref
    score: float
    reasons: list[str]
    creatives: str = "unknown"  # "same" | "different" | "unknown"


class MatrixCell(BaseModel):
    """Where one member has a trace: in the ad itself, on the landing page, or both."""

    ad: int = 0
    page: int = 0
    thumb: str | None = None  # the source picture (a face crop for persons)
    confidence: float | None = None  # for recognised persons and brands


class MatrixRow(BaseModel):
    """One shared trace and the members it occurs in (same order as the matrix columns)."""

    label: str
    raw: str | None = None
    mono: bool = False
    group: str
    entity_type: str = ""
    tier: str
    technical: bool = False  # paths and endpoints: kept out of the main view
    cells: list[MatrixCell] = []
    count: int


class Matrix(BaseModel):
    """Member x shared-trace matrix of a campaign."""

    columns: list[Ref]
    rows: list[MatrixRow]
    hidden: int = 0


class CompareCell(BaseModel):
    """A sentence with its neighbours, as found on one member's landing page."""

    text: str | None = None
    before: str = ""
    after: str = ""


class SharedRow(BaseModel):
    """One thing the members share, shown once;  are indices into the member list."""

    key: str
    label: str
    hint: str = ""
    style: str = "text"  # "text" | "badge" | "snippet" | "images" | "person"
    text: str | None = None
    mono: bool = False
    before: str = ""
    after: str = ""
    images: list[Thumb] = []
    thumb: str | None = None
    members: list[int] = []
    ad: int = 0  # reports where it is in the ad itself (persons, brands)
    page: int = 0  # reports where it is on the landing page
    confidence: float | None = None
    context: bool = False  # a hint for the analyst, not evidence


class DiffValue(BaseModel):
    """One of the values that vary between members."""

    text: str
    mono: bool = False
    members: list[int] = []


class DiffRow(BaseModel):
    """Something that differs between members: the distinct values, most common first."""

    key: str
    label: str
    hint: str = ""
    values: list[DiffValue] = []


class Variant(BaseModel):
    """One distinct ad picture and the members that use it (near-identical images merged)."""

    thumb: Thumb | None
    members: list[int]


class FaceRef(BaseModel):
    """A reference photo from the public-figure database, with its attribution."""

    url: str
    author: str
    license: str
    source_url: str


class Recognised(BaseModel):
    """A recognised public figure or brand, shown once for the whole campaign."""

    key: str
    kind: str  # "person" | "brand"
    name: str
    thumb: str | None = None  # the face as detected in the material
    reference: FaceRef | None = None  # the photo it was matched against
    similarity: float | None = None  # cosine similarity 0..1 (faces, logos); not a probability
    threshold: float | None = None
    method: str | None = None  # persons: "face" (picture) or "text" (named in the text only)
    matched: str | None = None  # method "text": the words that named the person
    members: list[int] = []
    ad: list[int] = []  # members where it is in the ad itself
    page: list[int] = []  # members where it is on the landing page


class Comparison(BaseModel):
    """What the members share (each thing once) and what varies between them."""

    same: list[SharedRow] = []
    different: list[DiffRow] = []
    variants: list[Variant] = []


class CampaignDetail(CampaignSummary):
    """Everything the campaign page shows."""

    verdict: str = ""
    comparison: Comparison = Comparison()
    recognised: list[Recognised] = []

    summary: list[str] = []
    pairs: list[PairLink] = []
    pairs_total: int = 0
    matrix: Matrix = Matrix(columns=[], rows=[])
    members: list[Member]
    constant: list[TraitRow]
    rotating_rows: list[TraitRow]
    evidence: list[FamilyEvidence]
    links: list[GroupLink]
    why: str


class FeatureRow(BaseModel):
    """A readable feature value in a case.

    `style` tells the UI how to show it: "value" (short values), "text" (long prose,
    collapsed) or "ocr" (noisy machine-read text, shown only on demand).
    """

    kind: str
    label: str
    style: str = "value"
    values: list[Value]
    total: int = 0


class FeatureFamily(BaseModel):
    """Features of one family in a case."""

    family: str
    label: str
    rows: list[FeatureRow]


class Neighbour(BaseModel):
    """A case linked to the selected case."""

    id: str
    title: str
    campaign: Ref | None
    score: float
    operator_link: bool
    families: dict[str, float | None]
    evidence: list[str]


class InputGroup(BaseModel):
    """Artifacts of one role in a case."""

    role: str
    label: str
    count: int
    names: list[str]


class CaseDetail(BaseModel):
    """Everything the case page shows."""

    id: str
    title: str
    corpus: str
    campaign: Ref | None
    operator: Ref | None
    domain: str | None
    captured_at: str | None
    duplicate_of: str | None
    flags: list[str]
    headline: str | None = None
    inputs: list[InputGroup]
    thumbs: list[Thumb]
    features: list[FeatureFamily]
    neighbours: list[Neighbour]
    # Public figures (by face or named in text) and brands seen in this report.
    recognised: list[Recognised] = []


class Summary(BaseModel):
    """Run totals and metadata for the overview page."""

    reports: int
    unique: int
    campaigns: int
    multi_campaigns: int
    operators: int
    toolkits: int
    corpora: dict[str, int]
    profile: str | None
    timings: dict[str, float]
    extractors: int
    features: int
    artifacts: int


class GraphNode(BaseModel):
    """A node pre-shaped for the force-graph UI."""

    id: str
    kind: str
    label: str
    size: float
    group: str | None = None
    group_index: int | None = None
    campaign: str | None = None
    tier: str | None = None
    entity_type: str | None = None
    detail: str | None = None
    thumb: str | None = None


class GraphLink(BaseModel):
    """An edge pre-shaped for the force-graph UI."""

    source: str
    target: str
    kind: str
    weight: float
    label: str


class GraphData(BaseModel):
    """Nodes and links of one graph view."""

    level: str
    nodes: list[GraphNode]
    links: list[GraphLink]
    hidden: int = 0


# ---------------------------------------------------------------- run data


class RunData:
    """A loaded run with lookup tables for readable values."""

    def __init__(self, run_dir: Path) -> None:
        store = RunStore(run_dir)
        self.run_dir = run_dir
        self.graph: Analysis = store.load_graph()
        self.cases: dict[str, Case] = {case.id: case for case in store.cases()}
        self.artifacts: list[Artifact] = store.artifacts()
        self.artifact_by_id: dict[tuple[str, str], Artifact] = {
            (a.case_id, a.id): a for a in self.artifacts
        }
        self.case_of_artifact: dict[str, str] = {a.id: a.case_id for a in self.artifacts}
        self.features: list[Feature] = store.features()
        self.entities = {entity.id: entity for entity in self.graph.entities}
        self.campaign_of: dict[str, Campaign] = {
            case: campaign for campaign in self.graph.campaigns for case in campaign.case_ids
        }
        self.campaigns = {campaign.id: campaign for campaign in self.graph.campaigns}
        self.family_of_type: dict[str, str] = {}
        for name, spec in FEATURES.items():
            entity_type = entity_type_for(name, spec)
            if entity_type and entity_type not in self.family_of_type:
                self.family_of_type[entity_type] = spec.family
        self._har_entries: dict[str, list[str]] = {}
        self.file_names = self._file_names()
        self._toolkit_groups()
        self.persons_of_case: dict[str, set[str]] = defaultdict(set)
        self.cases_of_entity: dict[str, set[str]] = defaultdict(set)
        self.entities_of_case: dict[str, set[str]] = defaultdict(set)
        for case, entity_id, _ in self.graph.links:
            self.cases_of_entity[entity_id].add(case)
            self.entities_of_case[case].add(entity_id)
            entity = self.entities.get(entity_id)
            if entity and entity.type == "Person":
                self.persons_of_case[case].add(entity.value)
        sizes: Counter[str] = Counter(self.graph.operators.values())
        ordered = sorted(sizes, key=lambda op: (-sizes[op], op))
        self.operator_index = {op: i for i, op in enumerate(ordered)}
        self.ocr_text: dict[str, str] = defaultdict(str)
        for feature in self.features:
            if feature.name in {"text.ocr", "ocr.headline"} and feature.value:
                self.ocr_text[feature.artifact_id] += " " + feature.value
        # Artifacts that captured an error page: their features describe the error, not the ad.
        self.error_artifacts: set[str] = {
            a for a, text in self.ocr_text.items() if _ERROR_PAGE.search(text)
        } | {
            f.artifact_id
            for f in self.features
            if f.name == "html.title" and _ERROR_PAGE.search(f.value)
        }
        self.thumbs = {case: self._case_thumbs(case) for case in self.graph.case_ids}
        self.face_refs = load_face_refs()
        self.picture_by_sha: dict[tuple[str, str], Artifact] = {}
        for artifact in self.artifacts:
            sha = artifact.meta.get("sha256")
            if (
                sha
                and artifact.kind in {"image", "asset"}
                and artifact.path.suffix.lower() in _IMAGE_SUFFIXES
            ):
                self.picture_by_sha.setdefault((artifact.case_id, sha), artifact)
        # Which features stand behind an entity in a case (for "where was it found").
        self.features_of: dict[tuple[str, str], list[Feature]] = defaultdict(list)
        for feature in self.features:
            known = FEATURES.get(feature.name)
            if known is None or not feature.value:
                continue
            entity_type = entity_type_for(feature.name, known)
            if entity_type:
                key = (feature.case_id, f"{entity_type}:{feature.value}")
                self.features_of[key].append(feature)
        self.pdq_of_case: dict[str, list[Feature]] = defaultdict(list)
        for feature in self.features:
            if feature.name == "img.pdq":
                self.pdq_of_case[feature.case_id].append(feature)

    @cached_property
    def case_traces(self) -> dict[str, CaseTraces]:
        """Persons (by face and by name in text), brands and domains of every base case."""
        from fakecollector.api.found import case_traces

        return case_traces(self.features)

    # ------------------------------------------------------------ readable values

    def _file_names(self) -> dict[str, str]:
        """Map an asset SHA-256 to a file name seen in the landing-page folder."""
        names: dict[str, str] = {}
        by_sha: dict[str, str] = {}
        for artifact in self.artifacts:
            sha = artifact.meta.get("sha256")
            rel = artifact.meta.get("rel") or artifact.path.name
            if sha and artifact.kind != "har":
                by_sha.setdefault(sha, PurePosixPath(rel.replace("\\", "/")).name)
        for feature in self.features:
            if feature.name != "asset.sha256" or feature.value in names:
                continue
            if feature.value in by_sha:
                names[feature.value] = by_sha[feature.value]
                continue
            found = self.artifact_by_id.get((feature.case_id, feature.artifact_id))
            if found is None:
                continue
            if found.kind != "har":
                names[feature.value] = found.path.name
            elif name := self._har_name(found, feature.locator):
                names[feature.value] = name
        return names

    def _har_name(self, artifact: Artifact, locator: str) -> str | None:
        """File name from the request URL of a HAR entry (parsed only, never fetched)."""
        match = _HAR_ENTRY.match(locator)
        if not match:
            return None
        entries = self._har_entries.get(artifact.id)
        if entries is None:
            entries = []
            try:
                if artifact.path.stat().st_size < 300 * 1024 * 1024:
                    loaded = json.loads(artifact.path.read_text(encoding="utf-8", errors="replace"))
                    entries = [
                        str(e.get("request", {}).get("url", ""))
                        for e in loaded.get("log", {}).get("entries", [])
                    ]
            except (OSError, ValueError, AttributeError):
                logger.warning("Cannot read HAR %s for file names", artifact.path)
            self._har_entries[artifact.id] = entries
        index = int(match.group(1))
        if index >= len(entries):
            return None
        path = urlsplit(entries[index]).path
        name = PurePosixPath(path).name
        return name or None

    def file_name(self, sha: str) -> str:
        """Return a file name for a hash, or a short hash label."""
        return self.file_names.get(sha) or pl.FILE_FALLBACK.format(short=sha[:10])

    def value(self, entity_type: str, value: str) -> Value:
        """Readable value of an entity, with the raw value kept for a tooltip."""
        if entity_type == "Asset":
            return Value(text=self.file_name(value), raw=value)
        if entity_type in {"Person", "Brand", "BrandLogo"}:
            return Value(text=display_value(entity_type, value))
        if entity_type in _DOMAIN_TYPES:
            return Value(text=defang(value), mono=True)
        if entity_type == "Endpoint":
            method, _, rest = value.partition(" ")
            text = f"{method} {defang(rest)}" if rest else defang(value)
            return Value(text=short(text), raw=value if len(text) > 56 else None, mono=True)
        if entity_type == "Narrative":
            return Value(text=human_label(value))
        if entity_type == "Topic":
            return Value(text=pl.TOPICS.get(value, value))
        if entity_type in {"KitLanding", "KitTenant"}:
            if len(value) <= 12:
                return Value(text=value, mono=True)
            return Value(text=f"{value[:8]}…", raw=value, mono=True)
        if entity_type == "ServerStack":
            return Value(text=value.replace("server=", "").replace("|via=", " / "))
        if entity_type in {"PathSignature", "Toolkit", "UrlSchema"}:
            text = value.replace("{uuid}", "…").replace("{n}", "#")
            return Value(text=short(text), raw=value, mono=True)
        if _HEX.fullmatch(value):
            return Value(text=f"{value[:10]}…", raw=value, mono=True)
        return Value(text=short(value), raw=value if len(value) > 56 else None)

    def type_label(self, entity_type: str) -> str:
        """Polish name of an entity type."""
        return pl.type_label(entity_type)

    def evidence_text(self, evidence: Evidence) -> Value:
        """Readable evidence line: file names for files, names for persons, short hashes."""
        spec = FEATURES.get(evidence.kind)
        if evidence.kind == "asset.sha256":
            return Value(text=self.file_name(evidence.value), raw=evidence.value)
        if spec and spec.entity_type and evidence.value:
            entity_type = entity_type_for(evidence.kind, spec) or spec.entity_type
            readable = self.value(entity_type, evidence.value)
            detail = evidence.detail.replace(evidence.value, readable.text)
        else:
            detail = evidence.detail
        detail = display_description("Person", detail)
        detail = detail.replace("{PERSON}", "[osoba]").replace("{NUM}", "[liczba]")
        detail = detail.replace("{uuid}", "…").replace("{n}", "#")
        detail = _HEX.sub(lambda m: m.group()[:10] + "…", detail)
        detail = detail.replace(" spraw)", " zgłoszeń)")
        return Value(text=detail, raw=evidence.value if _HEX.search(evidence.value) else None)

    # ------------------------------------------------------------ groups

    def operator_ref(self, operator: str | None) -> Ref | None:
        """Readable operator name: letters by size, A = largest."""
        if not operator:
            return None
        index = self.operator_index.get(operator)
        letter = chr(ord("A") + index) if index is not None and index < 26 else operator
        return Ref(id=operator, label=pl.OPERATOR.format(letter=letter))

    def toolkit_ref(self, toolkit: str) -> Ref:
        """Readable toolkit name from its defining entity."""
        entity_type, _, value = toolkit.partition(":")
        readable = self.value(entity_type, value)
        return Ref(id=toolkit, label=pl.TOOLKIT.format(name=readable.text))

    def _toolkit_groups(self) -> None:
        """Collapse toolkit entities seen in exactly the same cases into one named kit."""
        cases_of: dict[str, set[str]] = defaultdict(set)
        for case, kits in self.graph.toolkits.items():
            for kit in kits:
                if kit.partition(":")[0] not in _GENERIC_TOOLKIT_TYPES:
                    cases_of[kit].add(case)
        groups: dict[frozenset[str], list[str]] = defaultdict(list)
        for kit, cases in cases_of.items():
            groups[frozenset(cases)].append(kit)
        self.toolkit_members: dict[str, list[str]] = {}
        self.toolkit_rep: dict[str, str] = {}
        self.toolkit_cases: dict[str, set[str]] = {}
        for case_set, kits in groups.items():
            cases = set(case_set)
            kits.sort(key=lambda k: (not k.startswith("Toolkit:"), len(k), k))
            rep = kits[0]
            self.toolkit_members[rep] = kits
            self.toolkit_cases[rep] = set(cases)
            for kit in kits:
                self.toolkit_rep[kit] = rep

    def campaign_toolkits(self, campaign: Campaign) -> list[str]:
        """Named kits of a campaign (generic CDN libraries left out, duplicates collapsed)."""
        return unique(self.toolkit_rep[t] for t in campaign.toolkits if t in self.toolkit_rep)

    def campaign_operator(self, campaign: Campaign) -> str | None:
        """The campaign's operator, or the operator most of its members share."""
        if campaign.operator_id:
            return campaign.operator_id
        found = Counter(
            self.graph.operators[c] for c in campaign.case_ids if c in self.graph.operators
        )
        return found.most_common(1)[0][0] if found else None

    def campaign_label(self, campaign: Campaign) -> str:
        """Human campaign label; a masked person is named only when detected in all members."""
        persons = self._constant_persons(campaign)
        name = PERSON_DISPLAY_NAMES.get(persons[0], persons[0]) if len(persons) == 1 else None
        label = human_label(campaign.label, person=name)
        # Auto labels of new campaigns can carry a person slug: show the name instead.
        for slug, display in PERSON_DISPLAY_NAMES.items():
            if slug in label.lower():
                label = re.sub(re.escape(slug), display, label, flags=re.IGNORECASE)
        if _is_junk_label(label):
            return self._fallback_label(campaign, name)
        return label

    def _fallback_label(self, campaign: Campaign, person: str | None) -> str:
        """Readable stand-in for an unreadable OCR label."""
        count = len(campaign.case_ids)
        subject = person
        if not subject:
            domains = unique(
                d for d in (self._domain(self.cases.get(c)) for c in campaign.case_ids) if d
            )
            subject = domains[0] if domains else None
        reports = plural(count, pl.REPORTS)
        if subject:
            return f"Kampania: {subject} ({reports})"
        return f"Kampania bez czytelnego tytułu ({reports})"

    def _constant_persons(self, campaign: Campaign) -> list[str]:
        sets = [self.persons_of_case.get(case, set()) for case in campaign.case_ids]
        common = set.intersection(*sets) if sets else set()
        return sorted(common)

    def ref(self, campaign_id: str | None) -> Ref | None:
        """A campaign reference with its label."""
        campaign = self.campaigns.get(campaign_id or "")
        return Ref(id=campaign.id, label=self.campaign_label(campaign)) if campaign else None

    # ------------------------------------------------------------ thumbnails

    def _image_issue(self, artifact: Artifact) -> str | None:
        """Why an image is not ad material: an error page or a blank capture."""
        text = self.ocr_text.get(artifact.id, "")
        if _ERROR_PAGE.search(text):
            status = _STATUS.search(text)
            code = status.group(1) if status else None
            if code is None:
                code = next(
                    (
                        a.meta["landing_status"]
                        for a in self.artifacts
                        if a.case_id == artifact.case_id
                        and a.page == artifact.page
                        and a.meta.get("landing_status", "").startswith(("4", "5"))
                    ),
                    None,
                )
            return f"{pl.CAPTURE_ERROR_PAGE} ({code})" if code else pl.CAPTURE_ERROR_PAGE
        try:
            with Image.open(artifact.path) as image:
                spread = ImageStat.Stat(image.convert("L").resize((48, 48))).stddev[0]
        except (OSError, ValueError, Image.DecompressionBombError):
            return None
        return pl.BLANK_SCREENSHOT if spread < _BLANK_STDDEV else None

    def _case_thumbs(self, case_id: str) -> list[Thumb]:
        """Images of a case: ad creatives first, landing captures next, failed captures last."""
        images = [
            a
            for a in self.artifacts
            if a.case_id == case_id
            and a.kind == "image"
            and a.path.suffix.lower() in _IMAGE_SUFFIXES
            and a.path.is_file()
        ]
        rows: list[tuple[bool, int, bool, str, Artifact, str, str | None]] = []
        for a in images:
            issue = self._image_issue(a)
            if issue:
                self.error_artifacts.add(a.id)
            kind = "ad" if a.role == "ad_creative" else "landing" if a.page else "screenshot"
            rank = {"ad": 0, "screenshot": 1, "landing": 2}[kind]
            rows.append(
                (issue is not None, rank, a.parent_id is not None, str(a.path), a, kind, issue)
            )
        rows.sort(key=lambda row: row[:4])
        return [
            Thumb(
                case_id=case_id,
                artifact_id=a.id,
                url=f"/api/artifacts/{case_id}/{a.id}/thumb",
                name=a.path.name,
                kind=kind,
                kind_label=pl.THUMB_KINDS[kind],
                issue=issue,
            )
            for *_, a, kind, issue in rows
        ]

    def _good_thumbs(self, case_id: str) -> list[Thumb]:
        return [t for t in self.thumbs.get(case_id, []) if t.issue is None]

    def _first_thumb(self, case_id: str) -> Thumb | None:
        thumbs = self._good_thumbs(case_id)
        return thumbs[0] if thumbs else None

    def _thumb_url(self, case_id: str) -> str | None:
        thumb = self._first_thumb(case_id)
        return thumb.url if thumb else None

    def image_artifact(self, case_id: str, artifact_id: str) -> Artifact | None:
        """Return an image artifact of a case, or None for anything else."""
        artifact = self.artifact_by_id.get((case_id, artifact_id))
        if artifact is None or artifact.kind not in {"image", "asset"}:
            return None
        if artifact.path.suffix.lower() not in _IMAGE_SUFFIXES:
            return None
        return artifact

    # ------------------------------------------------------------ pages

    def summary(self, metadata: dict[str, object]) -> Summary:
        """Run totals."""
        corpora = Counter(case.corpus for case in self.cases.values())
        timings = metadata.get("timings_seconds")
        extractors = metadata.get("extractors")
        counts = metadata.get("counts")
        return Summary(
            reports=len(self.graph.case_ids),
            unique=sum(1 for c in self.graph.case_ids if not self._duplicate(c)),
            campaigns=len(self.graph.campaigns),
            multi_campaigns=sum(1 for c in self.graph.campaigns if len(c.case_ids) > 1),
            operators=len(set(self.graph.operators.values())),
            toolkits=sum(
                1
                for cases in self.toolkit_cases.values()
                if len({self.campaign_of[c].id for c in cases if c in self.campaign_of}) > 1
            ),
            corpora={pl.CORPUS_NAMES.get(k, k): v for k, v in sorted(corpora.items())},
            profile=str(metadata.get("profile")) if metadata.get("profile") else None,
            timings={str(k): float(v) for k, v in timings.items()}
            if isinstance(timings, dict)
            else {},
            extractors=len(extractors) if isinstance(extractors, dict) else 0,
            features=int(counts.get("features", 0)) if isinstance(counts, dict) else 0,
            artifacts=len(self.artifacts),
        )

    def _duplicate(self, case_id: str) -> str | None:
        case = self.cases.get(case_id)
        return case.duplicate_of if case else None

    def campaign_summary(self, campaign: Campaign) -> CampaignSummary:
        """Card data for one campaign."""
        operator = self.campaign_operator(campaign)
        rows = self.trait_rows(campaign)
        chips = []
        for row in rows:
            if row.kind != "constant" or row.entity_type in _NO_CHIP:
                continue
            chip = _CHIPS.get(row.entity_type)
            chips.append(chip if chip else row.headline)
        if len(campaign.case_ids) == 1:
            # A single report shares nothing with itself: show what identifies it instead.
            chips = [c for c in chips if not c[0].isdigit()]
        chips = unique(chips)[:4]
        # One image per member first, then further images, so cards rarely show gaps.
        thumbs = [t for case in campaign.case_ids for t in self._good_thumbs(case)[:1]]
        thumbs += [t for case in campaign.case_ids for t in self._good_thumbs(case)[1:3]]
        domains = unique(
            d for d in (self._domain(self.cases.get(c)) for c in campaign.case_ids) if d
        )
        persons = sorted(
            {
                display_value("Person", p)
                for case in campaign.case_ids
                for p in self.persons_of_case.get(case, set())
            }
        )
        return CampaignSummary(
            id=campaign.id,
            label=self.campaign_label(campaign),
            size=len(campaign.case_ids),
            operator=self.operator_ref(operator),
            operator_index=self.operator_index.get(operator) if operator else None,
            toolkits=[self.toolkit_ref(t) for t in self.campaign_toolkits(campaign)],
            chips=chips,
            rotating=[row.headline for row in rows if row.kind == "rotating"],
            persons=persons,
            cohesion=campaign.cohesion,
            thumbs=thumbs[:4],
            flags=[pl.flag_label(f) for f in campaign.flags],
            domains=domains,
            plain=self._plain_summary(campaign, rows, len(domains)),
        )

    def _plain_summary(self, campaign: Campaign, rows: list[TraitRow], domains: int) -> str:
        """One plain line for the overview: how many ads, how many addresses, what is shared."""
        n = len(campaign.case_ids)
        if n < 2:
            return pl.PLAIN_SINGLE
        parts = [plural(n, pl.ADS)]
        if domains > 1:
            parts.append(plural(domains, pl.DIFFERENT_DOMAINS))
        constant = {r.entity_type: r for r in rows if r.kind == "constant"}
        if "KitLanding" in constant:
            parts.append(pl.PLAIN_SAME_KIT_PAGE)
        elif "Asset" in constant:
            files = len(constant["Asset"].values)
            parts.append(pl.PLAIN_SAME_FILES.format(files=plural(files, pl.SAME_FILES)))
        elif "Narrative" in constant:
            parts.append(pl.PLAIN_SAME_HEADLINE)
        else:
            parts.append(pl.PLAIN_SIMILAR_PAGE)
        return ", ".join(parts)

    def campaign_list(self) -> list[CampaignSummary]:
        """All campaigns, largest first."""
        ordered = sorted(self.graph.campaigns, key=lambda c: (-len(c.case_ids), c.id))
        return [self.campaign_summary(c) for c in ordered]

    def trait_rows(self, campaign: Campaign) -> list[TraitRow]:
        """Readable traits: constant traits grouped per type, then rotating traits."""
        grouped: dict[str, list[Trait]] = defaultdict(list)
        rotating: list[Trait] = []
        for trait in campaign.traits:
            (grouped[trait.entity_type] if trait.kind == "constant" else rotating).append(trait)
        rows: list[TraitRow] = []
        for entity_type, items in grouped.items():
            values = [self.value(entity_type, t.value) for t in items]
            first = items[0]
            if entity_type == "Asset":
                # The profile keeps a few files per campaign; list every file all members share.
                known = {t.value for t in items}
                values += [self.value("Asset", sha) for sha in self._files_of_all(campaign) - known]
                # Descriptive names first; names that are just numbers say little.
                values.sort(key=lambda v: (v.text[:1].isdigit(), v.text.lower()))
            if entity_type == "Asset" and len(values) > 1:
                headline = plural(len(values), pl.ASSET_PLURAL)
            elif len(items) <= 3 and not any(v.mono or v.raw for v in values):
                headline = ", ".join(v.text for v in values)
            elif len(items) == 1:
                headline = values[0].text
            else:
                headline = f"{self.type_label(entity_type)}: {len(items)}"
            rows.append(self._row(entity_type, first, "constant", headline, values, items))
        members = set(campaign.case_ids)
        for trait in rotating:
            found = [
                (len(cases & members), entity.value)
                for entity_id, cases in self.cases_of_entity.items()
                if (entity := self.entities.get(entity_id)) is not None
                and entity.type == trait.entity_type
                and cases & members
            ]
            found.sort(key=lambda item: (-item[0], item[1]))
            values = [self.value(trait.entity_type, value) for _, value in found]
            headline = trait.value
            for word, plain in pl.PLAIN_WORDS.items():
                headline = re.sub(rf"\b{word}\b", plain, headline)
            row = self._row(trait.entity_type, trait, "rotating", headline, values, [trait])
            # The values are listed separately (defanged), so drop them from the sentence.
            start, end = row.why.find(" ("), row.why.rfind(")")
            if 0 <= start < end:
                row.why = row.why[:start] + row.why[end + 1 :]
            rows.append(row)
        return rows

    def _files_of_all(self, campaign: Campaign) -> set[str]:
        """Hashes of files present in every member of a campaign (common files left out)."""
        members = set(campaign.case_ids)
        if len(members) < 2:
            return set()
        found = set()
        for entity_id, cases in self.cases_of_entity.items():
            entity = self.entities.get(entity_id)
            if entity and entity.type == "Asset" and not entity.stop and members <= cases:
                found.add(entity.value)
        return found

    def _row(
        self,
        entity_type: str,
        trait: Trait,
        kind: str,
        headline: str,
        values: list[Value],
        items: list[Trait],
    ) -> TraitRow:
        family = self.family_of_type.get(entity_type, "")
        why = display_description(entity_type, trait.why)
        why = display_description("Person", why)
        why = _HEX.sub(lambda m: m.group()[:10] + "…", why)
        return TraitRow(
            entity_type=entity_type,
            type_label=self.type_label(entity_type),
            family=family,
            family_label=pl.family_label(family),
            tier=trait.tier,
            tier_label=pl.REPORT_TIERS.get(trait.tier, pl.REPORT_TIERS["context"]),
            kind=kind,
            headline=headline,
            values=values,
            coverage=min(t.coverage for t in items),
            lift=max(t.lift for t in items),
            why=why,
        )

    def campaign_edges(self, campaign: Campaign) -> list[Edge]:
        """Edges between members of a campaign."""
        members = set(campaign.case_ids)
        return [e for e in self.graph.edges if e.src in members and e.dst in members]

    def campaign_evidence(self, campaign: Campaign) -> list[FamilyEvidence]:
        """Evidence inside a campaign, aggregated by family and feature kind."""
        edges = self.campaign_edges(campaign)
        n = len(campaign.case_ids)
        total = n * (n - 1) // 2
        result = []
        for family in FAMILIES:
            fired = [e for e in edges if e.signals.get(family, 0.0) > 0 and family in e.comparable]
            if not fired:
                continue
            kinds: dict[str, list[tuple[Edge, Evidence]]] = defaultdict(list)
            for edge in fired:
                for item in edge.evidence:
                    if item.family == family:
                        kinds[item.kind].append((edge, item))
            rows = []
            for kind, items in kinds.items():
                seen: dict[str, Value] = {}
                for _, item in sorted(items, key=lambda pair: -pair[1].weight):
                    value = self.evidence_text(item)
                    seen.setdefault(value.text, value)
                rows.append(
                    EvidenceKind(
                        kind=kind,
                        label=pl.kind_label(kind),
                        tier=items[0][1].tier,
                        tier_label=pl.REPORT_TIERS.get(
                            items[0][1].tier, pl.REPORT_TIERS["context"]
                        ),
                        pairs=len({(e.src, e.dst) for e, _ in items}),
                        strength=max(i.weight for _, i in items),
                        values=list(seen.values())[:8],
                    )
                )
            rows.sort(key=lambda r: (-r.strength, -r.pairs))
            result.append(
                FamilyEvidence(
                    family=family,
                    label=pl.family_label(family),
                    pairs=len(fired),
                    total_pairs=total,
                    mean=sum(e.signals[family] for e in fired) / len(fired),
                    kinds=rows,
                )
            )
        result.sort(key=lambda f: (-f.pairs, -f.mean))
        return result

    def group_links(self, campaign: Campaign) -> list[GroupLink]:
        """Operator and toolkit links from this campaign to other campaigns."""
        links: list[GroupLink] = []
        members = set(campaign.case_ids)
        operator = self.campaign_operator(campaign)
        if operator:
            others = self._campaigns_where(lambda c: self.graph.operators.get(c) == operator)
            traces = self._operator_traces(operator, members)
            ref = self.operator_ref(operator)
            assert ref is not None
            links.append(
                GroupLink(
                    kind="operator",
                    id=operator,
                    label=ref.label,
                    campaigns=[r for r in others if r.id != campaign.id],
                    traces=traces,
                )
            )
        for toolkit in self.campaign_toolkits(campaign):
            kit_cases = self.toolkit_cases[toolkit]
            others = self._campaigns_where(lambda c, cases=kit_cases: c in cases)
            others = [r for r in others if r.id != campaign.id]
            if not others:
                continue
            traces = []
            for kit in self.toolkit_members[toolkit][:6]:
                entity_type, _, value = kit.partition(":")
                readable = self.value(entity_type, value)
                traces.append(
                    Value(
                        text=f"{self.type_label(entity_type)}: {readable.text}",
                        raw=readable.raw,
                        mono=True,
                    )
                )
            links.append(
                GroupLink(
                    kind="toolkit",
                    id=toolkit,
                    label=self.toolkit_ref(toolkit).label,
                    campaigns=others,
                    traces=traces,
                )
            )
        links = _merge_toolkits(links)
        links.sort(key=lambda link: (link.kind != "operator", -len(link.campaigns)))
        return links

    def _campaigns_where(self, predicate: object) -> list[Ref]:
        assert callable(predicate)
        found = []
        for campaign in self.graph.campaigns:
            if any(predicate(case) for case in campaign.case_ids):
                ref = self.ref(campaign.id)
                if ref:
                    found.append(ref)
        return found

    def _operator_traces(self, operator: str, members: set[str]) -> list[Value]:
        group_cases = {c for c, op in self.graph.operators.items() if op == operator}
        traces = []
        for entity in self.graph.entities:
            if entity.stop or entity.tier != "operator":
                continue
            cases = self.cases_of_entity.get(entity.id, set())
            if len(cases & group_cases) >= 2 and cases & members:
                readable = self.value(entity.type, entity.value)
                traces.append(
                    Value(
                        text=f"{self.type_label(entity.type)}: {readable.text}",
                        raw=readable.raw,
                        mono=False,
                    )
                )
        return traces[:8]

    def campaign_detail(self, campaign_id: str) -> CampaignDetail | None:
        """Everything the campaign page shows."""
        campaign = self.campaigns.get(campaign_id)
        if campaign is None:
            return None
        base = self.campaign_summary(campaign)
        rows = self.trait_rows(campaign)
        evidence = self.campaign_evidence(campaign)
        members = [self.member(case) for case in campaign.case_ids]
        pairs = self.campaign_pairs(campaign)
        return CampaignDetail(
            **base.model_dump(),
            verdict=self.campaign_verdict(campaign, rows, pairs),
            comparison=self.campaign_comparison(campaign, rows),
            recognised=self.campaign_recognised(campaign),
            summary=self.campaign_story(campaign, rows, pairs),
            pairs=pairs[:_MAX_PAIRS],
            pairs_total=len(pairs),
            matrix=self.campaign_matrix(campaign),
            members=members,
            constant=[r for r in rows if r.kind == "constant"],
            rotating_rows=[r for r in rows if r.kind == "rotating"],
            evidence=evidence,
            links=self.group_links(campaign),
            why=self._why(campaign, evidence),
        )

    def _why(self, campaign: Campaign, evidence: list[FamilyEvidence]) -> str:
        n = len(campaign.case_ids)
        if n == 1:
            return (
                "Pojedyncze zgłoszenie: żadne inne nie ma wystarczająco silnych wspólnych śladów."
            )
        strongest = [f.label for f in evidence[:3]]
        pairs = n * (n - 1) // 2
        linked = len(self.campaign_edges(campaign))
        return pl.WHY_LINKED.format(
            reports=plural(n, pl.REPORTS),
            linked=linked,
            pairs=plural(pairs, pl.POSSIBLE_PAIRS),
            families=", ".join(strongest),
        )

    def member(self, case_id: str) -> Member:
        """A case row in a campaign."""
        case = self.cases.get(case_id)
        corpus, _ = corpus_case(case_id)
        return Member(
            id=case_id,
            title=case_title(case_id),
            corpus=corpus,
            domain=self._domain(case),
            duplicate_of=case.duplicate_of if case else None,
            flags=[pl.flag_label(f) for f in (case.flags if case else [])],
            thumb=self._first_thumb(case_id),
        )

    @staticmethod
    def _domain(case: Case | None) -> str | None:
        if case is None or not case.landing_urls:
            return None
        url = case.landing_urls[0]
        host = url.split("://", 1)[-1].split("/", 1)[0]
        return defang(host) if host else None

    def case_detail(self, case_id: str) -> CaseDetail | None:
        """Everything the case page shows."""
        if case_id not in self.graph.case_ids and case_id not in self.cases:
            return None
        case = self.cases.get(case_id)
        corpus, _ = corpus_case(case_id)
        campaign = self.campaign_of.get(case_id)
        artifacts = [a for a in self.artifacts if a.case_id == case_id]
        by_role: dict[str, list[Artifact]] = defaultdict(list)
        for artifact in artifacts:
            by_role[artifact.role].append(artifact)
        inputs = [
            InputGroup(
                role=role,
                label=pl.ROLES.get(role, pl.UNKNOWN_ROLE),
                count=len(items),
                names=sorted({a.path.name for a in items})[:6]
                if role not in {"landing_asset"}
                else [],
            )
            for role, items in sorted(
                by_role.items(),
                key=lambda kv: list(pl.ROLES).index(kv[0]) if kv[0] in pl.ROLES else 99,
            )
        ]
        rows = neighbour_rows(self.graph, case_id)
        neighbours = [
            Neighbour(
                id=row.case_id,
                title=case_title(row.case_id),
                campaign=self.ref(self.campaign_of[row.case_id].id)
                if row.case_id in self.campaign_of
                else None,
                score=row.score,
                operator_link=row.operator_link,
                families=row.per_family,
                evidence=[
                    self.evidence_text(e).text
                    for e in sorted(
                        self._edge(case_id, row.case_id).evidence, key=lambda e: -e.weight
                    )[:3]
                ],
            )
            for row in rows
        ]
        operator = self.graph.operators.get(case_id)
        return CaseDetail(
            id=case_id,
            title=case_title(case_id),
            corpus=corpus,
            campaign=self.ref(campaign.id) if campaign else None,
            operator=self.operator_ref(operator),
            domain=self._domain(case),
            captured_at=case.captured_at.isoformat() if case and case.captured_at else None,
            duplicate_of=case.duplicate_of if case else None,
            flags=[pl.flag_label(f) for f in (case.flags if case else [])],
            inputs=inputs,
            headline=self.case_headline(case_id),
            thumbs=self.thumbs.get(case_id, [])[:12],
            features=self.case_features(case_id),
            neighbours=neighbours,
            recognised=self.recognised_in([case_id]),
        )

    def _edge(self, a: str, b: str) -> Edge:
        src, dst = sorted((a, b))
        return next(e for e in self.graph.edges if e.src == src and e.dst == dst)

    def case_features(self, case_id: str) -> list[FeatureFamily]:
        """Readable features of a case, grouped by family.

        Values read from failed captures (error pages) are left out, a value is shown once
        per family, and long or machine-read text is marked so the UI can collapse it.
        """
        values: dict[str, dict[str, dict[str, Value]]] = defaultdict(lambda: defaultdict(dict))
        for feature in self.features:
            if feature.case_id != case_id or not feature.value:
                continue
            if feature.name in _HIDDEN_FEATURES or feature.artifact_id in self.error_artifacts:
                continue
            spec = FEATURES.get(feature.name)
            if spec is None:
                continue
            if spec.family == "text" and _ERROR_PAGE.search(feature.value):
                continue
            entity_type = entity_type_for(feature.name, spec) or ""
            if feature.name in _LONG_TEXT or feature.name == "text.ocr":
                text = re.sub(r"\s+", " ", feature.value).strip()
                readable = Value(text=text[:_TEXT_LIMIT] + ("…" if len(text) > _TEXT_LIMIT else ""))
            elif feature.name == "asset.sha256":
                readable = Value(text=self.file_name(feature.value), raw=feature.value)
            elif feature.name == "ad.card_domain":
                readable = Value(text=defang(feature.value), mono=True)
            elif feature.name == "person.mentioned":
                readable = self.value("Person", feature.value)
            elif entity_type:
                readable = self.value(entity_type, feature.value)
            else:
                readable = Value(text=short(feature.value, 90))
            values[spec.family][feature.name].setdefault(readable.text.casefold(), readable)
        result = []
        for family in FAMILIES:
            kinds = values.get(family)
            if not kinds:
                continue
            seen: set[str] = set()
            rows = []
            for name, items in kinds.items():
                fresh = [v for key, v in items.items() if key not in seen]
                seen.update(items)
                if not fresh:
                    continue
                style = "text" if name in _LONG_TEXT else "ocr" if name in _OCR_TEXT else "value"
                rows.append(
                    FeatureRow(
                        kind=name,
                        label=pl.CASE_FEATURES.get(name, pl.FEATURE_KINDS.get(name, name)),
                        style=style,
                        values=fresh[:12],
                        total=len(fresh),
                    )
                )
            if rows:
                rows.sort(key=lambda row: {"value": 0, "text": 1, "ocr": 2}[row.style])
                result.append(
                    FeatureFamily(family=family, label=pl.family_label(family), rows=rows)
                )
        return result

    def case_headline(self, case_id: str) -> str | None:
        """A meaningful headline of a case: its page title, else its campaign's headline."""
        for feature in self.features:
            if feature.case_id != case_id or feature.name != "html.title":
                continue
            if feature.artifact_id in self.error_artifacts or _ERROR_PAGE.search(feature.value):
                continue
            title = re.sub(r"\s+", " ", feature.value).strip()
            if len(title.split()) >= 3:
                return title
        campaign = self.campaign_of.get(case_id)
        if campaign is None:
            return None
        label = self.campaign_label(campaign)
        return label if len(label.split()) >= 5 else None

    # ------------------------------------------------------------ graphs

    def campaign_graph(self) -> GraphData:
        """Campaigns as nodes; operator and specific toolkit links between campaigns."""
        nodes = []
        for campaign in self.graph.campaigns:
            operator = self.campaign_operator(campaign)
            ref = self.operator_ref(operator)
            nodes.append(
                GraphNode(
                    id=campaign.id,
                    kind="campaign",
                    label=self.campaign_label(campaign),
                    size=len(campaign.case_ids),
                    group=ref.label if ref else None,
                    group_index=self.operator_index.get(operator) if operator else None,
                    detail=", ".join(case_title(c) for c in campaign.case_ids[:6]),
                    thumb=self._thumb_url(campaign.case_ids[0]),
                )
            )
        links: list[GraphLink] = []
        campaigns = self.graph.campaigns
        for i, a in enumerate(campaigns):
            for b in campaigns[i + 1 :]:
                op_a, op_b = self.campaign_operator(a), self.campaign_operator(b)
                if op_a and op_a == op_b:
                    ref = self.operator_ref(op_a)
                    links.append(
                        GraphLink(
                            source=a.id,
                            target=b.id,
                            kind="operator",
                            weight=1.0,
                            label=ref.label if ref else "",
                        )
                    )
                    continue
                shared = set(self.campaign_toolkits(a)) & set(self.campaign_toolkits(b))
                if shared:
                    links.append(
                        GraphLink(
                            source=a.id,
                            target=b.id,
                            kind="toolkit",
                            weight=float(len(shared)),
                            label=f"Wspólne narzędzia: {len(shared)}",
                        )
                    )
        return GraphData(level="campaign", nodes=nodes, links=links)

    def case_graph(self, campaign_id: str | None) -> GraphData:
        """Cases as nodes, coloured by campaign; links are scored case-to-case edges."""
        cases = (
            self.campaigns[campaign_id].case_ids
            if campaign_id in self.campaigns
            else self.graph.case_ids
        )
        allowed = set(cases)
        nodes = []
        index = {c.id: i for i, c in enumerate(self.graph.campaigns)}
        for case_id in cases:
            campaign = self.campaign_of.get(case_id)
            thumbs = self.thumbs.get(case_id) or []
            nodes.append(
                GraphNode(
                    id=case_id,
                    kind="case",
                    label=case_title(case_id),
                    size=1,
                    group=self.campaign_label(campaign) if campaign else None,
                    group_index=index.get(campaign.id) if campaign else None,
                    campaign=campaign.id if campaign else None,
                    detail=self._domain(self.cases.get(case_id)),
                    thumb=thumbs[0].url if thumbs else None,
                )
            )
        links = [
            GraphLink(
                source=e.src,
                target=e.dst,
                kind="operator" if e.operator_link else "case",
                weight=e.score,
                label=", ".join(
                    pl.family_label(f)
                    for f in FAMILIES
                    if f in e.comparable and e.signals.get(f, 0.0) > 0
                ),
            )
            for e in self.graph.edges
            if e.src in allowed and e.dst in allowed
        ]
        return GraphData(level="case", nodes=nodes, links=links)

    def _shared_entities(
        self, campaign: Campaign, cap: int, per_type: int
    ) -> tuple[list[Entity], dict[str, set[str]], int]:
        """Most specific entities shared inside a campaign, strongest tier first."""
        members = set(campaign.case_ids)
        local: dict[str, set[str]] = defaultdict(set)
        for case, entity_id, _ in self.graph.links:
            if case in members:
                local[entity_id].add(case)
        tier_rank = {"campaign": 0, "operator": 1, "toolkit": 2, "context": 3}
        minimum = 2 if len(members) > 1 else 1
        candidates = []
        for entity_id, cases in local.items():
            entity = self.entities.get(entity_id)
            if entity is None or entity.stop or len(cases) < minimum:
                continue
            if entity.df > max(3, len(members) * 2) and entity.tier in {"toolkit", "context"}:
                continue
            candidates.append((tier_rank[entity.tier], -len(cases), entity.df, entity_id))
        candidates.sort()
        # Many files of one template say the same thing: keep a few per type.
        seen: Counter[str] = Counter()
        kept = []
        for item in candidates:
            entity = self.entities[item[3]]
            if seen[entity.type] >= per_type:
                continue
            seen[entity.type] += 1
            kept.append(entity)
            if len(kept) >= cap:
                break
        return kept, local, len(candidates) - len(kept)

    def campaign_matrix(self, campaign: Campaign, cap: int = 60) -> Matrix:
        """Members of a campaign against the traces they share (rows: strongest tier first)."""
        columns = [Ref(id=case, label=case_title(case)) for case in campaign.case_ids]
        if len(columns) < 2:
            return Matrix(columns=columns, rows=[])
        kept, local, hidden = self._shared_entities(campaign, cap=cap, per_type=12)
        rows = []
        for entity in kept:
            if entity.type in _RECOGNISED_TYPES:
                # Persons and brands are context: shown once in their own section.
                continue
            readable = self.value(entity.type, entity.value)
            cells = [
                self._matrix_cell(case, entity) if case in local[entity.id] else MatrixCell()
                for case in campaign.case_ids
            ]
            rows.append(
                MatrixRow(
                    label=readable.text,
                    raw=readable.raw,
                    mono=readable.mono,
                    group=self.type_label(entity.type),
                    entity_type=entity.type,
                    tier=entity.tier,
                    technical=entity.type in _TECHNICAL_TYPES,
                    cells=cells,
                    count=sum(1 for case in campaign.case_ids if case in local[entity.id]),
                )
            )
        return Matrix(columns=columns, rows=rows, hidden=hidden)

    def _in_ad(self, artifact: Artifact | None) -> bool:
        """Whether an artifact is the ad itself (creative, ad screenshot), not the landing page."""
        if artifact is None:
            return False
        if artifact.role in _AD_ROLES:
            return True
        return artifact.role == "screenshot" and not artifact.page

    def _matrix_cell(self, case_id: str, entity: Entity) -> MatrixCell:
        """Where in a case an entity was seen, with a picture of the source when there is one."""
        found = self.features_of.get((case_id, entity.id), [])
        if not found:
            # Derived entities (no direct feature): present, source unknown.
            return MatrixCell(page=1)
        ad = [f for f in found if self._in_ad(self.artifact_by_id.get((case_id, f.artifact_id)))]
        page = [f for f in found if f not in ad]
        cell = MatrixCell(ad=len(ad), page=len(page))
        if entity.type in _RECOGNISED_TYPES:
            cell.confidence = max(f.confidence for f in found)
        if entity.type not in {"Asset", "Person", "Brand", "BrandLogo"}:
            return cell
        # Prefer the ad as the source picture, then the most confident match.
        for best in sorted(found, key=lambda f: (f not in ad, -f.confidence)):
            artifact = self.image_artifact(case_id, best.artifact_id)
            if artifact is None or not artifact.path.is_file():
                continue
            base = f"/api/artifacts/{case_id}/{artifact.id}"
            box = _BBOX.search(best.locator)
            if entity.type == "Person" and box:
                cell.thumb = f"{base}/crop?bbox={box.group(1)}"
            else:
                cell.thumb = f"{base}/thumb"
            break
        if cell.thumb is None and entity.type == "Asset":
            picture = self.picture_by_sha.get((case_id, entity.value))
            if picture is not None:
                cell.thumb = f"/api/artifacts/{case_id}/{picture.id}/thumb"
        return cell

    # ------------------------------------------------------------ why one campaign

    def _creative_hashes(self, case_id: str) -> list[int]:
        """PDQ hashes of the ad material of a case (creatives and ad screenshots)."""
        wanted = {t.artifact_id for t in self._good_thumbs(case_id) if t.kind != "landing"}
        hashes = []
        for feature in self.pdq_of_case.get(case_id, []):
            if feature.artifact_id in wanted:
                try:
                    hashes.append(int(feature.value, 16))
                except ValueError:
                    continue
        return hashes

    def creative_relation(self, a: str, b: str) -> str:
        """Whether two cases show the same ad creative: "same", "different" or "unknown"."""
        left, right = self._creative_hashes(a), self._creative_hashes(b)
        if not left or not right:
            return "unknown"
        distance = min((x ^ y).bit_count() for x in left for y in right)
        if distance <= _PDQ_SAME:
            return "same"
        return "different" if distance >= _PDQ_DIFFERENT else "unknown"

    def _pair_reasons(self, edge: Edge, creatives: str = "unknown") -> list[str]:
        """Short Polish reasons for one edge, strongest first (evidence tiers only)."""
        by_kind: dict[str, list[Evidence]] = defaultdict(list)
        for item in edge.evidence:
            if item.tier in {"campaign", "operator"}:
                by_kind[item.kind].append(item)
        ranked = sorted(by_kind.items(), key=lambda kv: -max(i.weight for i in kv[1]))
        reasons = []
        for kind, items in ranked:
            phrase = self._reason(kind, items)
            if kind in {"img.pdq", "img.phash"} and creatives == "different":
                # The ads differ, so the identical picture is one used on the landing pages.
                phrase = pl.SAME_IMAGE_ON_LANDING
            if phrase and phrase not in reasons:
                reasons.append(phrase)
        return reasons[:4]

    @staticmethod
    def _reason(kind: str, items: list[Evidence]) -> str | None:
        if kind == "asset.sha256":
            return plural(len(items), pl.IDENTICAL_FILES)
        if kind in pl.SIMILARITY_REASONS:
            found = [s for s in (_similarity(i.value) for i in items) if s is not None]
            if not found:
                return None
            return pl.SIMILARITY_REASONS[kind].format(percent=round(max(found) * 100))
        if kind in pl.PAIR_REASONS:
            return pl.PAIR_REASONS[kind]
        label = pl.FEATURE_KINDS.get(kind)
        return label[0].lower() + label[1:] if label else None

    def campaign_pairs(self, campaign: Campaign) -> list[PairLink]:
        """Linked member pairs of a campaign, strongest first."""
        edges = sorted(self.campaign_edges(campaign), key=lambda e: -e.score)
        pairs = []
        for e in edges:
            creatives = self.creative_relation(e.src, e.dst)
            pairs.append(
                PairLink(
                    a=Ref(id=e.src, label=case_title(e.src)),
                    b=Ref(id=e.dst, label=case_title(e.dst)),
                    score=e.score,
                    reasons=self._pair_reasons(e, creatives),
                    creatives=creatives,
                )
            )
        return pairs

    def campaign_story(
        self, campaign: Campaign, rows: list[TraitRow], pairs: list[PairLink]
    ) -> list[str]:
        """Two to four plain sentences: why these reports are one campaign."""
        n = len(campaign.case_ids)
        if n < 2:
            return []
        edges = self.campaign_edges(campaign)
        file_rows = [r for r in rows if r.kind == "constant" and r.entity_type == "Asset"]
        files = sum(len(r.values) for r in file_rows)
        text = [
            max(found)
            for e in edges
            if (
                found := [
                    s
                    for i in e.evidence
                    if i.kind == "text.minhash" and (s := _similarity(i.value)) is not None
                ]
            )
        ]
        landing = []
        if files:
            landing.append(plural(files, pl.IDENTICAL_FILES_INSTR))
        if text and len(text) == len(edges):
            percent = round(min(text) * 100)
            if percent >= 100:
                landing.append(pl.STORY_TEXT_IDENTICAL)
            else:
                prefix = "" if len(text) == 1 else pl.AT_LEAST
                landing.append(pl.STORY_TEXT.format(prefix=prefix, percent=percent))
        kinds = {i.kind for e in edges for i in e.evidence}
        ids = [phrase for kind, phrase in pl.STORY_IDS.items() if kind in kinds]
        relations = Counter(p.creatives for p in pairs)
        different, same = relations["different"], relations["same"]
        who = pl.STORY_BOTH if n == 2 else pl.STORY_ALL.format(count=n)
        story = []
        if landing:
            lead = pl.STORY_LEAD_DIFFERENT if different else pl.STORY_LEAD_SAME
            story.append(lead.format(who=who, traces=_join(landing)))
        elif ids:
            story.append(pl.STORY_LEAD_IDS.format(traces=_join(ids[:2])))
            ids = []
        elif pairs and pairs[0].reasons:
            story.append(pl.STORY_LEAD_OTHER.format(traces=_join(pairs[0].reasons[:3])))
        if different and same:
            story.append(pl.STORY_CREATIVES_MIXED)
        elif different:
            story.append(pl.STORY_CREATIVES_DIFFERENT)
        elif same:
            story.append(pl.STORY_CREATIVES_SAME)
        if ids:
            story.append(pl.STORY_IDS_EXTRA.format(traces=_join(ids[:3])))
        rotating = [r.headline for r in rows if r.kind == "rotating"]
        if rotating:
            story.append(pl.STORY_ROTATING.format(values=_join(rotating[:4])))
        return story[:4]

    def campaign_verdict(
        self, campaign: Campaign, rows: list[TraitRow], pairs: list[PairLink]
    ) -> str:
        """The one-sentence answer a newcomer should take away from the campaign page."""
        n = len(campaign.case_ids)
        if n < 2:
            return pl.VERDICT_SINGLE
        subject = (
            pl.VERDICT_SUBJECT_FEW if plural_word(n, ("a", "b", "c")) == "b" else pl.VERDICT_SUBJECT
        )
        subject = subject.format(count=n, ads=plural_word(n, pl.ADS))
        relations = {p.creatives for p in pairs}
        shared_page = any(
            r.kind == "constant" and r.entity_type in {"Asset", "KitLanding"} for r in rows
        ) or any(
            i.kind == "text.minhash" for e in self.campaign_edges(campaign) for i in e.evidence
        )
        if not shared_page:
            return pl.VERDICT_TRACES.format(subject=subject)
        if "different" in relations:
            tail = pl.VERDICT_LOOK_DIFFERENT
        elif relations == {"same"}:
            tail = pl.VERDICT_LOOK_SAME
        else:
            tail = ""
        return pl.VERDICT_SAME_PAGE.format(subject=subject, tail=tail)

    def _page_texts(self, case_id: str) -> list[str]:
        """Landing-page texts of a case, longest first (error pages left out)."""
        texts = [
            f.value
            for f in self.features
            if f.case_id == case_id
            and f.name == "text.raw"
            and f.artifact_id not in self.error_artifacts
            and not _ERROR_PAGE.search(f.value[:400])
        ]
        return sorted(texts, key=len, reverse=True)

    def _shared_snippet(self, cases: list[str]) -> list[CompareCell] | None:
        """A sentence found on every member's landing page, with each member's own context."""
        pages = []
        for case in cases:
            texts = self._page_texts(case)
            if not texts:
                return None
            pages.append([s.strip() for t in texts[:3] for s in _SENTENCE.split(t) if s.strip()])
        norm = [{_norm(s): i for i, s in reversed(list(enumerate(page)))} for page in pages]
        shared = [
            s
            for s in pages[0]
            if 70 <= len(s) <= 220 and _prose(s) and all(_norm(s) in other for other in norm[1:])
        ]
        if not shared:
            return None
        # The first prose sentences are the article itself; footers and legal text come last.
        best = max(shared[:6], key=len)
        cells = []
        for page, index in zip(pages, norm, strict=True):
            at = index[_norm(best)]
            before = page[at - 1] if at > 0 else ""
            after = page[at + 1] if at + 1 < len(page) else ""
            cells.append(
                CompareCell(
                    text=page[at],
                    before=("…" + before[-70:]) if len(before) > 70 else before,
                    after=(after[:70] + "…") if len(after) > 70 else after,
                )
            )
        return cells

    def _shared_pictures(self, campaign: Campaign, limit: int = 4) -> dict[str, list[Thumb]]:
        """Pictures from the landing pages that are byte-identical in every member."""
        by_case: dict[str, dict[str, Artifact]] = defaultdict(dict)
        members = set(campaign.case_ids)
        for artifact in self.artifacts:
            sha = artifact.meta.get("sha256")
            if (
                sha
                and artifact.case_id in members
                and artifact.kind in {"image", "asset"}
                and artifact.path.suffix.lower() in _IMAGE_SUFFIXES
            ):
                by_case[artifact.case_id].setdefault(sha, artifact)
        common = self._files_of_all(campaign)
        for case in campaign.case_ids:
            common &= set(by_case[case])
        first = by_case[campaign.case_ids[0]] if campaign.case_ids else {}

        def size(sha: str) -> int:
            try:
                return first[sha].path.stat().st_size
            except OSError:
                return 0

        # Bigger files are photos and screenshots; tiny ones are icons that prove little.
        chosen = sorted(common, key=lambda sha: (-size(sha), sha))[:limit]
        return {
            case: [
                Thumb(
                    case_id=case,
                    artifact_id=by_case[case][sha].id,
                    url=f"/api/artifacts/{case}/{by_case[case][sha].id}/thumb",
                    name=self.file_name(sha),
                    kind="landing",
                    kind_label=pl.THUMB_KINDS["landing"],
                )
                for sha in chosen
            ]
            for case in campaign.case_ids
        }

    def _values_of(self, case_id: str, entity_type: str) -> list[Value]:
        return [
            self.value(entity_type, entity.value)
            for entity_id in sorted(self.entities_of_case.get(case_id, ()))
            if (entity := self.entities.get(entity_id)) is not None and entity.type == entity_type
        ]

    def campaign_recognised(self, campaign: Campaign) -> list[Recognised]:
        """Public figures and brands seen in a campaign: each once, with where it was seen."""
        return self.recognised_in(campaign.case_ids)

    def _named_persons(self, cases: list[str], seen: set[str]) -> list[Recognised]:
        """Persons only named in the text of these cases (no face match): context entries."""
        named: dict[str, dict[int, str]] = defaultdict(dict)
        for i, case in enumerate(cases):
            traces = self.case_traces.get(case)
            if traces is None:
                continue
            for slug in traces.names - seen:
                named[slug][i] = ""
        if not named:
            return []
        words: dict[str, str] = {}
        wanted = set(cases)
        for feature in self.features:
            if (
                feature.name == "person.mentioned"
                and feature.value in named
                and feature.case_id in wanted
            ):
                quoted = re.search(r"„(.*)”", feature.locator)
                if quoted:
                    words.setdefault(feature.value, quoted.group(1))
        out = []
        for slug, where in named.items():
            out.append(
                Recognised(
                    key=f"PersonMention:{slug}",
                    kind="person",
                    name=self.value("Person", slug).text,
                    reference=self.face_refs.get(slug),
                    method="text",
                    matched=words.get(slug),
                    members=sorted(where),
                )
            )
        return out

    def recognised_in(self, cases: list[str]) -> list[Recognised]:
        """Public figures (by face, or named in text) and brands seen in these cases."""
        found: list[Recognised] = []
        for entity_id in sorted(self.entities):
            entity = self.entities[entity_id]
            if entity.type not in _RECOGNISED_TYPES:
                continue
            cells = {
                i: self._matrix_cell(case, entity)
                for i, case in enumerate(cases)
                if case in self.cases_of_entity.get(entity_id, set())
            }
            if not cells:
                continue
            person = entity.type == "Person"
            best = max(cells.values(), key=lambda c: (c.ad > 0, c.confidence or 0.0))
            scored = person or entity.type == "BrandLogo"
            found.append(
                Recognised(
                    key=entity_id,
                    kind="person" if person else "brand",
                    name=self.value(entity.type, entity.value).text,
                    thumb=best.thumb if person else None,
                    reference=self.face_refs.get(entity.value) if person else None,
                    similarity=max((c.confidence or 0.0) for c in cells.values())
                    if scored
                    else None,
                    threshold=FACE_THRESHOLD if person else None,
                    method="face" if person else None,
                    members=sorted(cells),
                    ad=sorted(i for i, c in cells.items() if c.ad),
                    page=sorted(i for i, c in cells.items() if c.page),
                )
            )
        people = [r.key for r in found if r.kind == "person"]
        by_face = {self.entities[key].value for key in people if key in self.entities}
        found += self._named_persons(cases, by_face)
        found.sort(key=lambda r: (r.kind != "person", r.method == "text", -len(r.members), r.name))
        return found

    def _creative_variants(self, cases: list[str]) -> list[Variant]:
        """Distinct ad pictures of a campaign: near-identical creatives count as one variant."""
        hashes = {case: self._creative_hashes(case) for case in cases}
        parent = list(range(len(cases)))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i, a in enumerate(cases):
            for j in range(i + 1, len(cases)):
                left, right = hashes[a], hashes[cases[j]]
                if (
                    left
                    and right
                    and min((x ^ y).bit_count() for x in left for y in right) <= (_PDQ_SAME)
                ):
                    parent[find(j)] = find(i)
        groups: dict[int, list[int]] = defaultdict(list)
        missing: list[int] = []
        for index, case in enumerate(cases):
            if hashes[case] and self._first_thumb(case) is not None:
                groups[find(index)].append(index)
            else:
                missing.append(index)
        variants = [
            Variant(thumb=self._first_thumb(cases[members[0]]), members=members)
            for members in sorted(groups.values(), key=lambda m: (-len(m), m[0]))
        ]
        if missing:
            variants.append(Variant(thumb=None, members=missing))
        return variants

    def _diff_row(self, key: str, label: str, hint: str, per_case: list[list[Value]]) -> DiffRow:
        """Distinct values of one thing across the members, most common first."""
        seen: dict[str, DiffValue] = {}
        for index, values in enumerate(per_case):
            for value in values:
                item = seen.setdefault(value.text, DiffValue(text=value.text, mono=value.mono))
                if index not in item.members:
                    item.members.append(index)
        ordered = sorted(seen.values(), key=lambda v: (-len(v.members), v.text))
        return DiffRow(key=key, label=label, hint=hint, values=ordered)

    def campaign_comparison(self, campaign: Campaign, rows: list[TraitRow]) -> Comparison:
        """What the members share (each thing shown once, with its coverage) and what varies."""
        cases = campaign.case_ids
        if len(cases) < 2:
            return Comparison()
        everyone = list(range(len(cases)))
        same: list[SharedRow] = []
        constant = {r.entity_type: r for r in rows if r.kind == "constant"}

        def having(entity_type: str, texts: set[str]) -> list[int]:
            return [
                i
                for i, case in enumerate(cases)
                if any(v.text in texts for v in self._values_of(case, entity_type))
            ]

        files = len(constant["Asset"].values) if "Asset" in constant else 0
        if files:
            pictures = self._shared_pictures(campaign).get(cases[0], [])
            names = ", ".join(v.text for v in constant["Asset"].values[:3])
            same.append(
                SharedRow(
                    key="files",
                    label=pl.COMPARE_FILES,
                    hint=pl.COMPARE_FILES_HINT.format(files=plural(files, pl.IDENTICAL_FILES)),
                    style="images" if pictures else "text",
                    images=pictures,
                    text=None if pictures else names,
                    members=everyone,
                )
            )
        snippet = self._shared_snippet(cases)
        if snippet:
            found = [
                s
                for e in self.campaign_edges(campaign)
                for i in e.evidence
                if i.kind == "text.minhash" and (s := _similarity(i.value)) is not None
            ]
            hint = (
                pl.COMPARE_TEXT_HINT.format(percent=round(min(found) * 100))
                if found
                else pl.COMPARE_TEXT_HINT_PLAIN
            )
            first = snippet[0]
            same.append(
                SharedRow(
                    key="text",
                    label=pl.COMPARE_TEXT,
                    hint=hint,
                    style="snippet",
                    text=first.text,
                    before=first.before,
                    after=first.after,
                    members=everyone,
                )
            )
        titles = [
            {
                f.value.strip()
                for f in self.features
                if f.case_id == case
                and f.name == "html.title"
                and f.value.strip()
                and not _ERROR_PAGE.search(f.value)
            }
            for case in cases
        ]
        common_titles = set.intersection(*titles) if titles else set()
        if common_titles:
            same.append(
                SharedRow(
                    key="title",
                    label=pl.COMPARE_TITLE,
                    hint=pl.COMPARE_TITLE_HINT,
                    text=short(max(common_titles, key=len), 110),
                    members=everyone,
                )
            )
        if "Narrative" in constant and not common_titles:
            row = constant["Narrative"]
            same.append(
                SharedRow(
                    key="headline",
                    label=pl.COMPARE_HEADLINE,
                    hint=pl.COMPARE_HEADLINE_HINT,
                    text=row.values[0].text if row.values else row.headline,
                    members=having("Narrative", {v.text for v in row.values}) or everyone,
                )
            )
        for entity_type, (label, hint) in pl.COMPARE_IDS.items():
            id_row = constant.get(entity_type)
            if id_row is None:
                continue
            for value in id_row.values[:2]:
                same.append(
                    SharedRow(
                        key=f"{entity_type}:{value.text}",
                        label=label,
                        hint=hint,
                        style="badge",
                        text=value.text,
                        mono=True,
                        members=having(entity_type, {value.text}),
                    )
                )
        variants = self._creative_variants(cases)
        different: list[DiffRow] = []
        domains = [self._domain(self.cases.get(case)) for case in cases]
        domain_row = self._diff_row(
            "domain",
            pl.COMPARE_DOMAIN,
            pl.COMPARE_DOMAIN_HINT,
            [[Value(text=d, mono=True)] if d else [] for d in domains],
        )
        if len(domain_row.values) > 1:
            different.append(domain_row)
        rotating = {r.entity_type for r in rows if r.kind == "rotating"}
        for entity_type, (label, hint) in pl.COMPARE_ROTATING.items():
            if entity_type not in rotating:
                continue
            diff = self._diff_row(
                entity_type, label, hint, [self._values_of(case, entity_type) for case in cases]
            )
            if len(diff.values) > 1:
                different.append(diff)
        return Comparison(same=same, different=different, variants=variants)

    def entity_graph(self, campaign_id: str, cap: int = 40) -> GraphData:
        """Cases of one campaign and the most specific entities they share."""
        campaign = self.campaigns.get(campaign_id)
        if campaign is None:
            return GraphData(level="entity", nodes=[], links=[])
        kept, local, hidden = self._shared_entities(campaign, cap=cap, per_type=6)
        nodes = [
            GraphNode(
                id=case_id,
                kind="case",
                label=case_title(case_id),
                size=2,
                campaign=campaign_id,
                detail=self._domain(self.cases.get(case_id)),
                thumb=self._thumb_url(case_id),
            )
            for case_id in campaign.case_ids
        ]
        links = []
        for entity in kept:
            readable = self.value(entity.type, entity.value)
            nodes.append(
                GraphNode(
                    id=entity.id,
                    kind="entity",
                    label=readable.text,
                    size=len(local[entity.id]),
                    tier=entity.tier,
                    entity_type=entity.type,
                    group=self.type_label(entity.type),
                    detail=f"{self.type_label(entity.type)} · {pl.REPORT_TIERS.get(entity.tier)}"
                    f" · {pl.IN_REPORTS.format(count=plural(entity.df, pl.REPORTS_LOCATIVE))}",
                )
            )
            for case in sorted(local[entity.id]):
                links.append(
                    GraphLink(
                        source=case,
                        target=entity.id,
                        kind=entity.tier,
                        weight=1.0,
                        label=self.type_label(entity.type),
                    )
                )
        return GraphData(level="entity", nodes=nodes, links=links, hidden=hidden)


def _role_rank(role: str) -> int:
    roles = list(pl.ROLES)
    return roles.index(role) if role in roles else len(roles)


def _merge_toolkits(links: list[GroupLink]) -> list[GroupLink]:
    """One card per set of linked campaigns: kit files seen together say the same thing."""
    merged: dict[tuple[str, ...], GroupLink] = {}
    result = []
    for link in links:
        if link.kind != "toolkit":
            result.append(link)
            continue
        key = tuple(sorted(r.id for r in link.campaigns))
        if key in merged:
            merged[key].traces.extend(link.traces)
            continue
        merged[key] = link.model_copy(deep=True)
        result.append(merged[key])
    for link in merged.values():
        link.traces = link.traces[:8]
        link.label = pl.TOOLKIT_SHARED.format(count=len(link.campaigns) + 1)
    return result


_PLACEHOLDERS = {"liczba", "osoba", "n", "[osoba]", "[liczba]", "tys", "mln"}
_JUNK_PHRASES = ("powered by", "see more", "sponsored")


def _is_junk_label(label: str) -> bool:
    """True when a generated label is mostly placeholders or OCR noise."""
    lowered = label.lower()
    if any(phrase in lowered for phrase in _JUNK_PHRASES):
        return True
    words = re.findall(r"[^\W\d_]+|\[\w+\]", lowered)
    real = [
        w for w in words if w not in _PLACEHOLDERS and len(w) >= 3 and re.search("[aeiouyąę]", w)
    ]
    holders = [w for w in words if w in _PLACEHOLDERS]
    return len(real) < 3 or len(holders) > len(real)


def human_label(label: str, person: str | None = None) -> str:
    """Readable campaign label from an auto label or a headline template."""
    text = label.replace("{PERSON}", "[osoba]").replace("{NUM}", pl.NUMBER_TOKEN)
    text = re.sub(r"\s+:\s*", ": ", text).strip(" _-")
    text = re.sub(r"\s{2,}", " ", text)
    if person:
        text = text.replace("[osoba]", person)
    if text:
        text = text[0].upper() + text[1:]
        text = re.sub(r"([.!?] )([a-ząćęłńóśźż])", lambda m: m.group(1) + m.group(2).upper(), text)
    return text


def unique(values: Iterable[str]) -> list[str]:
    """Order-preserving de-duplication."""
    return list(dict.fromkeys(values))
