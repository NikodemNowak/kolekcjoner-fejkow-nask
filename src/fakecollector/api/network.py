"""The whole run as one network: reports, campaigns and the traces they share.

Reports are nodes clustered by campaign; persons, brands, infrastructure, templates and
operators are optional trace nodes. Every link carries the readable reason it exists, so the
UI can answer "why are these connected" for any edge.
"""

from __future__ import annotations

import io
import json
import re
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel

from fakecollector.api import pl
from fakecollector.api.views import RunData, case_title, face_ref_file

# Trace kinds shown as nodes and the entity types behind them.
KIND_OF_TYPE = {
    "Person": "person",
    "Brand": "brand",
    "BrandLogo": "brand",
    "Domain": "infra",
    "Host": "infra",
    "Endpoint": "infra",
    "Tracker": "infra",
    "Advertiser": "infra",
    "AdvertiserPage": "infra",
    "AdLibraryId": "infra",
    "ShortLink": "infra",
    "Phone": "infra",
    "BankAccount": "infra",
    "Messenger": "infra",
    "KitTenant": "infra",
    "IP": "infra",
    "ClickKey": "infra",
    "Toolkit": "template",
    "PathSignature": "template",
    "UrlSchema": "template",
    "KitLanding": "template",
    "Asset": "template",
    "Narrative": "template",
}
# At most this many trace nodes per kind (most widely shared first) keep the map readable.
CAP_PER_KIND = {"person": 80, "brand": 40, "infra": 90, "template": 90}
# Assets are many files of one page template: a few per campaign are enough.
ASSETS_PER_CAMPAIGN = 3
MAX_PAIRS_PER_REPORT = 4
WHERE = {
    (True, False): "w reklamie",
    (False, True): "na stronie docelowej",
    (True, True): "w reklamie i na stronie docelowej",
}


class NetNode(BaseModel):
    """A report or a trace on the network map."""

    id: str
    kind: str  # report | person | brand | infra | template | operator
    label: str
    detail: str | None = None
    campaign: str | None = None
    group_index: int | None = None
    image: str | None = None
    count: int = 1
    mono: bool = False
    tier: str | None = None
    tier_label: str | None = None


class NetLink(BaseModel):
    """Why two nodes are connected."""

    source: str
    target: str
    kind: str  # pair (report-report) | trace (report-trace) | operator (report-operator)
    tier: str | None = None
    strength: float = 1.0
    reasons: list[str] = []
    where: str | None = None
    confidence: float | None = None


class NetCampaign(BaseModel):
    """A campaign cluster on the map."""

    id: str
    label: str
    size: int
    group_index: int | None = None
    operator: str | None = None


class Network(BaseModel):
    """Everything the network view draws."""

    nodes: list[NetNode]
    links: list[NetLink]
    campaigns: list[NetCampaign]
    hidden: dict[str, int] = {}


# (minus report count, tier rank, entity id, reports): sorts the most shared, strongest first.
Candidate = tuple[int, int, str, set[str]]


def _face_url(slug: str) -> str | None:
    return f"/api/faces/{slug}/ref" if face_ref_file(slug) else None


def build_network(data: RunData) -> Network:
    """Reports, campaign clusters and shared traces of the loaded run."""
    nodes: list[NetNode] = []
    links: list[NetLink] = []
    campaigns: list[NetCampaign] = []
    operator_of_campaign: dict[str, int | None] = {}
    for campaign in data.graph.campaigns:
        operator = data.campaign_operator(campaign)
        ref = data.operator_ref(operator)
        index = data.operator_index.get(operator) if operator else None
        operator_of_campaign[campaign.id] = index
        campaigns.append(
            NetCampaign(
                id=campaign.id,
                label=data.campaign_label(campaign),
                size=len(campaign.case_ids),
                group_index=index,
                operator=ref.label if ref else None,
            )
        )
        for case_id in campaign.case_ids:
            nodes.append(
                NetNode(
                    id=case_id,
                    kind="report",
                    label=case_title(case_id),
                    detail=data._domain(data.cases.get(case_id)),
                    campaign=campaign.id,
                    group_index=index,
                    image=data._thumb_url(case_id),
                )
            )
    reports = {n.id for n in nodes}

    # Report-to-report links: the strongest scored pairs of each report.
    per_report: dict[str, int] = defaultdict(int)
    for edge in sorted(data.graph.edges, key=lambda e: -e.score):
        if edge.src not in reports or edge.dst not in reports:
            continue
        same = data.campaign_of.get(edge.src) is data.campaign_of.get(edge.dst)
        if not same and not edge.operator_link:
            continue
        if (
            per_report[edge.src] >= MAX_PAIRS_PER_REPORT
            and per_report[edge.dst] >= MAX_PAIRS_PER_REPORT
        ):
            continue
        per_report[edge.src] += 1
        per_report[edge.dst] += 1
        reasons = data._pair_reasons(edge)
        if not same:
            reasons = [pl.REPORT_TIERS["operator"], *reasons]
        links.append(
            NetLink(
                source=edge.src,
                target=edge.dst,
                kind="pair",
                tier="campaign" if same else "operator",
                strength=round(edge.score, 3),
                reasons=reasons,
            )
        )

    # Operators ("Sprawca A"): one node each, linked to its reports with the traces behind it.
    members_of: dict[str, set[str]] = defaultdict(set)
    for case_id, operator in data.graph.operators.items():
        if case_id in reports:
            members_of[operator].add(case_id)
    for operator, members in sorted(
        members_of.items(), key=lambda kv: data.operator_index.get(kv[0], 99)
    ):
        ref = data.operator_ref(operator)
        traces = [t.text for t in data._operator_traces(operator, members)]
        nodes.append(
            NetNode(
                id=f"op:{operator}",
                kind="operator",
                label=ref.label if ref else operator,
                detail=pl.REPORT_TIERS["operator"],
                group_index=data.operator_index.get(operator),
                count=len(members),
                tier="operator",
                tier_label=pl.REPORT_TIERS["operator"],
            )
        )
        for case_id in sorted(members):
            links.append(
                NetLink(
                    source=case_id,
                    target=f"op:{operator}",
                    kind="operator",
                    tier="operator",
                    reasons=traces[:5],
                )
            )

    # Shared traces.
    candidates: dict[str, list[Candidate]] = defaultdict(list)
    assets_kept: dict[str, int] = defaultdict(int)
    for entity_id, cases in data.cases_of_entity.items():
        entity = data.entities.get(entity_id)
        if entity is None or entity.stop:
            continue
        kind = KIND_OF_TYPE.get(entity.type)
        if kind is None:
            continue
        cases = cases & reports
        recognised = kind in {"person", "brand"}
        if not cases or (len(cases) < 2 and not recognised):
            continue
        # Generic infrastructure (a CDN, a common library) links everything to everything.
        if (
            not recognised
            and entity.tier in {"toolkit", "context"}
            and len(cases) > max(6, len(reports) // 5)
        ):
            continue
        tier_rank = {"campaign": 0, "operator": 1, "toolkit": 2, "context": 3}.get(entity.tier, 4)
        candidates[kind].append((-len(cases), tier_rank, entity_id, cases))
    # One brand node per name: a brand named in text and its logo are the same trace.
    merged: dict[str, tuple[int, int, str, set[str], list[str]]] = {}
    for item in candidates.pop("brand", []):
        entity = data.entities[item[2]]
        key = data.value(entity.type, entity.value).text.casefold()
        if key in merged:
            prev = merged[key]
            cases = prev[3] | item[3]
            logo = prev[2] if data.entities[prev[2]].type == "BrandLogo" else item[2]
            merged[key] = (-len(cases), min(prev[1], item[1]), logo, cases, prev[4] + [item[2]])
        else:
            merged[key] = (*item, [item[2]])
    candidates["brand"] = [m[:4] for m in merged.values()]
    also = {m[2]: m[4] for m in merged.values()}
    hidden: dict[str, int] = {}
    for kind, items in candidates.items():
        items.sort()
        kept = 0
        for _, _, entity_id, cases in items:
            entity = data.entities[entity_id]
            sources = [data.entities[e] for e in also.get(entity_id, [entity_id])]
            if entity.type == "Asset":
                owners = {data.campaign_of[c].id for c in cases if c in data.campaign_of}
                if all(assets_kept[o] >= ASSETS_PER_CAMPAIGN for o in owners):
                    hidden[kind] = hidden.get(kind, 0) + 1
                    continue
                for o in owners:
                    assets_kept[o] += 1
            if kept >= CAP_PER_KIND[kind]:
                hidden[kind] = hidden.get(kind, 0) + 1
                continue
            kept += 1
            readable = data.value(entity.type, entity.value)
            image = None
            if entity.type == "Person":
                image = _face_url(entity.value)
            nodes.append(
                NetNode(
                    id=entity_id,
                    kind=kind,
                    label=readable.text,
                    detail=data.type_label(entity.type),
                    count=len(cases),
                    mono=readable.mono,
                    image=image,
                    tier=entity.tier,
                    tier_label=pl.REPORT_TIERS.get(entity.tier),
                )
            )
            for case_id in sorted(cases):
                owner = next(
                    (e for e in sources if case_id in data.cases_of_entity.get(e.id, set())), entity
                )
                cell = data._matrix_cell(case_id, owner)
                if image is None and cell.thumb and owner.type in {"Person", "BrandLogo"}:
                    image = cell.thumb
                    nodes[-1].image = image
                where = WHERE.get((cell.ad > 0, cell.page > 0))
                links.append(
                    NetLink(
                        source=case_id,
                        target=entity_id,
                        kind="trace",
                        tier=entity.tier,
                        where=where,
                        confidence=round(cell.confidence, 3) if cell.confidence else None,
                    )
                )
    return Network(nodes=nodes, links=links, campaigns=campaigns, hidden=hidden)


_CACHE: list[tuple[RunData, Network]] = []


def cached_network(data: RunData) -> Network:
    """The network of a loaded run, built once per load (keyed by the object, not its id)."""
    if not _CACHE or _CACHE[0][0] is not data:
        _CACHE[:] = [(data, build_network(data))]
    return _CACHE[0][1]


def collector_report(run_dir: Path) -> dict[str, object] | None:
    """The last automatic collector report (`<run>/collector/last.json`), if any."""
    path = run_dir / "collector" / "last.json"
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


_ITEM_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_COLLECTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_MAX_COLLECTED_BYTES = 20 * 1024 * 1024


def collector_image(run_dir: Path, item_id: str, width: int) -> bytes | None:
    """A re-encoded JPEG of one collected ad screenshot (`<run>/collector/inbox/<id>/zrzut.*`)."""
    if not _ITEM_ID.fullmatch(item_id) or ".." in item_id:
        return None
    folder = run_dir / "collector" / "inbox" / item_id
    if not folder.is_dir():
        return None
    for path in sorted(folder.glob("zrzut.*")):
        if path.suffix.lower() not in _COLLECTED_SUFFIXES or path.is_symlink():
            continue
        try:
            if path.stat().st_size > _MAX_COLLECTED_BYTES:
                return None
            with Image.open(path) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((width, width * 3))
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=82)
                return output.getvalue()
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
            return None
    return None
