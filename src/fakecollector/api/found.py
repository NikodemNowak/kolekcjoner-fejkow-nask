"""What was recognised in analysed material, and which known campaigns it resembles.

Frontend contract (new, optional fields of `Verdict`; older clients can ignore them):

    found: {
      persons: [{slug, name, method: "face" | "text", method_label,
                 similarity: 0.82 | null, similarity_text: "0,82" | null, threshold,
                 matched: "Obajtkiem" | null,          # text: the words that named the person
                 crop: "data:image/jpeg;base64,…" | null,  # face: the face as detected
                 reference: FaceRef | null,            # photo it was matched against
                 campaigns: [Ref], reports: 3}],       # base campaigns with the same person
      brands: [{slug, name, method: "logo" | "brand" | "text", method_label, similarity}],
      domains: ["example[.]com"],                     # web addresses seen (URL or OCR)
      headline: "Obajtek był częścią systemu…" | null,
    }
    similar: [{campaign: Ref, score: 0.0-1.0, reports: 6,
               traces: ["ta sama osoba: Daniel Obajtek (wzmianka w tekście)", …]}]

`found` is filled for every decision, also "new": it tells the user what the tool saw. A face
match and a name in the text are separate entries (`method`), never merged. Persons and brands
are context only: they never make an `existing` link (one celebrity is reused by many
unrelated campaigns); `similar` lists them as leads next to the real evidence score.
"""

from __future__ import annotations

import base64
import io
import re
from collections import defaultdict
from dataclasses import dataclass, field

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel

from fakecollector.api import pl
from fakecollector.api.views import FaceRef, Ref, RunData, defang
from fakecollector.app.display import display_value
from fakecollector.core.schemas import Artifact, Evidence, Feature
from fakecollector.extractors.person_text import FEATURE_NAME as MENTION
from fakecollector.extractors.person_text import TEXT_SOURCES, find_mentions, fold

FACE = "person.public_figure"
BRAND_FEATURES = {"brand.impersonated": "brand", "brand.logo": "logo"}
DOMAIN_FEATURES = {"url.domain", "ocr.domain"}
MAX_SIMILAR = 5
MAX_TRACES = 6
MAX_CROP_BYTES = 40 * 1024 * 1024
CROP_WIDTH = 96
_BBOX = re.compile(r"bbox=(-?\d+),(-?\d+),(\d+),(\d+)")
_LOCATOR_WORDS = re.compile(r"„(.*)”")


class FoundPerson(BaseModel):
    """A public figure seen in the material: by face or named in the text."""

    slug: str
    name: str
    method: str  # "face" | "text"
    method_label: str
    similarity: float | None = None  # face: cosine similarity 0..1, not a probability
    similarity_text: str | None = None  # "0,82"
    threshold: float | None = None
    matched: str | None = None  # text: the words that named the person
    crop: str | None = None  # face: small JPEG data URI of the detected face
    reference: FaceRef | None = None
    campaigns: list[Ref] = []  # known campaigns with the same person (context, not evidence)
    reports: int = 0  # known reports with the same person


class FoundBrand(BaseModel):
    """A brand or logo recognised in the material."""

    slug: str
    name: str
    method: str  # "logo" | "brand" (picture) | "text" (named in the text)
    method_label: str
    similarity: float | None = None


class Found(BaseModel):
    """Everything recognised in one analysed input, whatever the decision."""

    persons: list[FoundPerson] = []
    brands: list[FoundBrand] = []
    domains: list[str] = []
    headline: str | None = None


class SimilarCampaign(BaseModel):
    """A known campaign close to the input, with the traces both share."""

    campaign: Ref
    score: float  # evidence score towards this campaign (persons and brands add nothing)
    reports: int
    traces: list[str]


@dataclass
class CaseTraces:
    """Readable traces of one case: persons (by face / by name), brands, domains."""

    faces: dict[str, float] = field(default_factory=dict)
    names: set[str] = field(default_factory=set)
    brands: set[str] = field(default_factory=set)
    domains: set[str] = field(default_factory=set)

    @property
    def persons(self) -> set[str]:
        """Persons seen in any way."""
        return set(self.faces) | self.names


def case_traces(features: list[Feature]) -> dict[str, CaseTraces]:
    """Traces per case; names in text are also found in runs built before `person.mentioned`."""
    out: dict[str, CaseTraces] = defaultdict(CaseTraces)
    for f in features:
        if not f.value:
            continue
        traces = out[f.case_id]
        if f.name == FACE:
            traces.faces[f.value] = max(traces.faces.get(f.value, 0.0), f.confidence)
        elif f.name == MENTION:
            traces.names.add(f.value)
        elif f.name in BRAND_FEATURES:
            traces.brands.add(f.value)
        elif f.name in DOMAIN_FEATURES:
            traces.domains.add(f.value)
        elif f.name in TEXT_SOURCES:
            traces.names.update(m.slug for m in find_mentions(f.value))
    return dict(out)


# Brand names that are distinctive in text; generic ones ("ING", "WP", "Facebook" in every
# feed screenshot) are left to the logo matchers.
_TEXT_BRANDS: dict[str, str] = {
    "tvn24": r"tvn ?24",
    "gazeta_pl": r"gazeta\.pl",
    "onet": r"onet(?:\.pl)?",
    "inpost": r"inpost\w*",
    "pko_bp": r"pko ?bp|pko bank polski",
    "pekao": r"pekao",
    "nbp": r"nbp|narodow\w+ bank\w* polski\w*",
    "allegro": r"allegro",
    "mbank": r"mbank\w*",
    "santander": r"santander",
    "millennium": r"bank\w* millennium",
    "alior": r"alior",
    "interia": r"interia",
    "polsat": r"polsat\w*",
    "tvp": r"tvp(?: info)?",
    "rzeczpospolita": r"rzeczpospolit\w*",
    "business_insider": r"business insider",
    "forbes": r"forbes\w*",
    "zus": r"zus(?:u|ie|em)?",
    "orlen": r"orlen\w*",
    "revolut": r"revolut\w*",
    "binance": r"binance",
    "olx": r"olx",
}
_TEXT_BRAND_PATTERNS = {
    slug: re.compile(rf"(?<![a-z0-9]){regex}(?![a-z0-9])") for slug, regex in _TEXT_BRANDS.items()
}


def brands_in_text(text: str) -> list[str]:
    """Brands named in text (folded, word-bounded), in a stable order."""
    if not text:
        return []
    folded = fold(text)
    return [slug for slug, pattern in _TEXT_BRAND_PATTERNS.items() if pattern.search(folded)]


def similarity_text(value: float) -> str:
    """0.8213 -> "0,82" (Polish decimal comma)."""
    return f"{value:.2f}".replace(".", ",")


def face_crop(path: str, bbox: tuple[int, int, int, int], width: int = CROP_WIDTH) -> str | None:
    """A small JPEG data URI of a face (square with margin); None if the image is unusable."""
    from pathlib import Path

    x, y, w, h = bbox
    source = Path(path)
    try:
        if w <= 0 or h <= 0 or not source.is_file() or source.stat().st_size > MAX_CROP_BYTES:
            return None
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            side = int(max(w, h) * 1.5)
            cx, cy = x + w // 2, y + h // 2
            left = max(0, min(cx - side // 2, image.width - side))
            top = max(0, min(cy - side // 2, image.height - side))
            box = (left, top, min(image.width, left + side), min(image.height, top + side))
            if box[2] - box[0] < 4 or box[3] - box[1] < 4:
                return None
            image = image.crop(box)
            image.thumbnail((width, width))
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=85)
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        return None
    return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def _bbox(locator: str) -> tuple[int, int, int, int] | None:
    match = _BBOX.search(locator)
    if not match:
        return None
    x, y, w, h = (int(v) for v in match.groups())
    return x, y, w, h


def _person_campaigns(slug: str, data: RunData) -> tuple[list[Ref], int]:
    """Known campaigns (largest first) and reports in which the same person appears."""
    traces = data.case_traces
    cases = [case for case, t in traces.items() if slug in t.persons]
    sizes: dict[str, int] = defaultdict(int)
    for case in cases:
        campaign = data.campaign_of.get(case)
        if campaign is not None:
            sizes[campaign.id] += 1
    order = sorted(sizes, key=lambda c: (-sizes[c], c))
    refs = [ref for c in order[:3] if (ref := data.ref(c)) is not None]
    return refs, len(cases)


def build_found(
    case_id: str,
    features: list[Feature],
    artifacts: list[Artifact],
    data: RunData,
    face_threshold: float,
) -> Found:
    """What the tool recognised in one new case (its own features only)."""
    mine = [f for f in features if f.case_id == case_id]
    paths = {a.id: str(a.path) for a in artifacts if a.case_id == case_id}
    persons: list[FoundPerson] = []
    best_face: dict[str, Feature] = {}
    for f in mine:
        known = best_face.get(f.value)
        if f.name == FACE and f.value and (known is None or f.confidence > known.confidence):
            best_face[f.value] = f
    for slug, f in sorted(best_face.items(), key=lambda kv: -kv[1].confidence):
        box = _bbox(f.locator)
        path = paths.get(f.artifact_id)
        campaigns, reports = _person_campaigns(slug, data)
        persons.append(
            FoundPerson(
                slug=slug,
                name=display_value("Person", slug),
                method="face",
                method_label=pl.FOUND_METHODS["face"],
                similarity=round(f.confidence, 4),
                similarity_text=similarity_text(f.confidence),
                threshold=face_threshold,
                crop=face_crop(path, box) if path and box else None,
                reference=data.face_refs.get(slug),
                campaigns=campaigns,
                reports=reports,
            )
        )
    named: dict[str, str] = {}
    for f in mine:
        if f.name == MENTION and f.value and f.value not in named:
            quoted = _LOCATOR_WORDS.search(f.locator)
            named[f.value] = quoted.group(1) if quoted else ""
    if not named:  # material analysed by an older pipeline: read the names from its text
        for f in mine:
            if f.name in TEXT_SOURCES:
                for m in find_mentions(f.value):
                    named.setdefault(m.slug, m.matched)
    for slug, words in named.items():
        campaigns, reports = _person_campaigns(slug, data)
        persons.append(
            FoundPerson(
                slug=slug,
                name=display_value("Person", slug),
                method="text",
                method_label=pl.FOUND_METHODS["text"],
                matched=words or None,
                reference=data.face_refs.get(slug),
                campaigns=campaigns,
                reports=reports,
            )
        )
    brands: dict[tuple[str, str], FoundBrand] = {}
    for f in mine:
        method = BRAND_FEATURES.get(f.name)
        if method and f.value:
            key = (f.value, method)
            if key not in brands or (brands[key].similarity or 0.0) < f.confidence:
                brands[key] = FoundBrand(
                    slug=f.value,
                    name=display_value("Brand", f.value),
                    method=method,
                    method_label=pl.FOUND_METHODS[method],
                    similarity=round(f.confidence, 4),
                )
    text = " ".join(f.value for f in mine if f.name in TEXT_SOURCES and f.value)
    for slug in brands_in_text(text):
        if not any(b.slug == slug for b in brands.values()):
            brands[(slug, "text")] = FoundBrand(
                slug=slug,
                name=display_value("Brand", slug),
                method="text",
                method_label=pl.FOUND_METHODS["text"],
            )
    domains = sorted({defang(f.value) for f in mine if f.name in DOMAIN_FEATURES and f.value})
    headline = next((f.value for f in mine if f.name == "ocr.headline" and f.value), None)
    if headline is None:
        headline = next((f.value for f in mine if f.name == "html.title" and f.value), None)
    return Found(
        persons=persons,
        brands=sorted(brands.values(), key=lambda b: (b.name, b.method)),
        domains=domains,
        headline=headline,
    )


def build_similar(
    case_id: str,
    features: list[Feature],
    evidence: list[Evidence],
    data: RunData,
) -> list[SimilarCampaign]:
    """The closest known campaigns: evidence score first, then shared persons/brands/domains."""
    new = case_traces([f for f in features if f.case_id == case_id]).get(case_id, CaseTraces())
    score: dict[str, float] = defaultdict(float)
    traces: dict[str, list[str]] = defaultdict(list)
    for item in evidence:
        line = pl.TRACE_EVIDENCE.format(
            label=pl.kind_label(item.kind), text=data.evidence_text(item).text
        )
        for ref in item.artifacts:
            case = data.case_of_artifact.get(ref.split("#", 1)[0])
            campaign = data.campaign_of.get(case) if case else None
            if campaign is None:
                continue
            score[campaign.id] = max(score[campaign.id], item.weight)
            if item.weight > 0 and line not in traces[campaign.id]:
                traces[campaign.id].append(line)
    context: dict[str, list[str]] = defaultdict(list)
    for case, base in data.case_traces.items():
        campaign = data.campaign_of.get(case)
        if campaign is None:
            continue
        lines = context[campaign.id]
        shared: list[tuple[str, str]] = []  # (name the evidence would use, trace line)
        for slug in sorted(new.persons & base.persons):
            name = display_value("Person", slug)
            method = "face" if slug in new.faces else "text"  # how it is seen in the input
            shared.append(
                (name, pl.TRACE_PERSON.format(name=name, method=pl.FOUND_METHODS[method]))
            )
        for brand in sorted(new.brands & base.brands):
            name = display_value("Brand", brand)
            shared.append((name, pl.TRACE_BRAND.format(name=name)))
        for domain in sorted(new.domains & base.domains):
            shared.append((domain, pl.TRACE_DOMAIN.format(domain=defang(domain))))
        evidence_lines = " ".join(traces.get(campaign.id, []))
        for name, line in shared:
            # Already said by an evidence line (e.g. "Wspólna marka w materiałach: Gazeta.pl").
            if line not in lines and name not in evidence_lines:
                lines.append(line)
    candidates = {c for c in score if score[c] > 0} | {c for c, lines in context.items() if lines}
    ranked = sorted(candidates, key=lambda c: (-score.get(c, 0.0), -len(context.get(c, [])), c))
    out: list[SimilarCampaign] = []
    for campaign_id in ranked[:MAX_SIMILAR]:
        target = data.ref(campaign_id)
        if target is None:
            continue
        out.append(
            SimilarCampaign(
                campaign=target,
                score=round(score.get(campaign_id, 0.0), 4),
                reports=len(data.campaigns[campaign_id].case_ids),
                traces=(traces.get(campaign_id, []) + context.get(campaign_id, []))[:MAX_TRACES],
            )
        )
    return out
