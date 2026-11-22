"""Build a self-contained analyst report from a persisted analysis."""

from __future__ import annotations

import base64
import io
import json
import logging
from collections import defaultdict
from importlib.resources import files
from pathlib import Path

from jinja2 import Environment, select_autoescape
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel

from fakecollector.app import pl
from fakecollector.app.display import (
    display_campaign_label,
    display_description,
    display_evidence,
    display_value,
)
from fakecollector.app.group_evidence import GroupEvidence, group_evidence
from fakecollector.core.schemas import Artifact, Case, Trait
from fakecollector.graph.analyze import Analysis
from fakecollector.report.graph import GraphLabels, defang, render_graph
from fakecollector.store import RunStore

logger = logging.getLogger(__name__)
_MAX_THUMBNAIL_BYTES = 20 * 1024 * 1024
_MAX_THUMBNAIL_PIXELS = 50_000_000


class ReportCase(BaseModel):
    """A case label, optional duplicate reference and safe local thumbnail."""

    label: str
    duplicate_of: str | None
    thumbnail: str | None


class ReportEvidence(BaseModel):
    """One explanatory trace with its source artifacts."""

    cases: str
    family: str
    detail: str
    weight: float
    artifacts: list[str]


class ReportCampaign(BaseModel):
    """Campaign information prepared for the HTML template."""

    id: str
    label: str
    operator: str | None
    members: list[ReportCase]
    traits: list[Trait]
    evidence: list[ReportEvidence]


class ReportGroup(BaseModel):
    """Operator or toolkit and its associated cases."""

    label: str
    cases: list[str]
    evidence: list[GroupEvidence]


class ReportData(BaseModel):
    """All analyst-facing data for one report."""

    summary: str
    campaigns: list[ReportCampaign]
    operators: list[ReportGroup]
    toolkits: list[ReportGroup]


def _thumbnail(artifact: Artifact) -> str | None:
    """Load and downscale a local image; missing or unsafe images are skipped."""
    try:
        path = artifact.path
        if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_THUMBNAIL_BYTES:
            logger.warning("Thumbnail skipped for %s: unavailable or unsafe file", path)
            return None
        with Image.open(path) as source:
            if source.width * source.height > _MAX_THUMBNAIL_PIXELS:
                logger.warning("Thumbnail skipped for %s: image too large", path)
                return None
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((240, 160))
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=80)
        return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode("ascii")
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        logger.warning("Thumbnail skipped for %s", artifact.path, exc_info=True)
        return None


def _report_case(case_id: str, cases: dict[str, Case], artifacts: list[Artifact]) -> ReportCase:
    case = cases.get(case_id)
    images = sorted(
        (a for a in artifacts if a.case_id == case_id and a.kind == "image"),
        key=lambda a: (a.role not in {"screenshot", "ad_creative"}, str(a.path)),
    )
    thumbnail = next((image for artifact in images if (image := _thumbnail(artifact))), None)
    return ReportCase(
        label=defang(case_id),
        duplicate_of=defang(case.duplicate_of) if case and case.duplicate_of else None,
        thumbnail=thumbnail,
    )


def _groups(
    mapping: dict[str, list[str]], evidence: dict[str, list[GroupEvidence]]
) -> list[ReportGroup]:
    return [
        ReportGroup(
            label=defang(name),
            cases=sorted(defang(case) for case in case_ids),
            evidence=[
                item.model_copy(
                    update={
                        "value": defang(item.value),
                        "sources": [
                            source.model_copy(
                                update={
                                    "case_id": defang(source.case_id),
                                    "artifacts": [
                                        defang(artifact) for artifact in source.artifacts
                                    ],
                                }
                            )
                            for source in item.sources
                        ],
                    }
                )
                for item in evidence.get(name, [])
            ],
        )
        for name, case_ids in sorted(mapping.items())
    ]


def report_data(store: RunStore, graph: Analysis) -> ReportData:
    """Build report sections from typed cases, artifacts and graph evidence."""
    cases = {case.id: case for case in store.cases()}
    artifacts = store.artifacts()
    operator_ids = set(graph.operators.values()) | {
        campaign.operator_id for campaign in graph.campaigns if campaign.operator_id
    }
    summary = pl.REPORT_SUMMARY.format(
        cases=len(graph.case_ids),
        unique=sum(not case.duplicate_of for case in cases.values()),
        campaigns=len(graph.campaigns),
        operators=len(operator_ids),
    )
    campaigns = []
    for campaign in graph.campaigns:
        members = set(campaign.case_ids)
        evidence = [
            ReportEvidence(
                cases=f"{defang(edge.src)} ↔ {defang(edge.dst)}",
                family=pl.FAMILY_NAMES.get(item.family, item.family),
                detail=defang(display_evidence(item)),
                weight=item.weight,
                artifacts=[defang(ref) for ref in item.artifacts],
            )
            for edge in graph.edges
            if edge.src in members and edge.dst in members
            for item in edge.evidence
        ]
        traits = [
            trait.model_copy(
                update={
                    "value": defang(display_value(trait.entity_type, trait.value)),
                    "why": defang(display_description(trait.entity_type, trait.why)),
                }
            )
            for trait in campaign.traits
        ]
        campaigns.append(
            ReportCampaign(
                id=defang(campaign.id),
                label=defang(display_campaign_label(campaign.label or campaign.id)),
                operator=defang(campaign.operator_id) if campaign.operator_id else None,
                members=[_report_case(case, cases, artifacts) for case in campaign.case_ids],
                traits=traits,
                evidence=evidence,
            )
        )
    operators: dict[str, list[str]] = defaultdict(list)
    for case, operator in graph.operators.items():
        operators[operator].append(case)
    toolkits: dict[str, list[str]] = defaultdict(list)
    for case, names in graph.toolkits.items():
        for name in names:
            toolkits[name].append(case)
    shared = group_evidence(graph)
    return ReportData(
        summary=summary,
        campaigns=campaigns,
        operators=_groups(operators, shared["operator"]),
        toolkits=_groups(toolkits, shared["toolkit"]),
    )


def build_report(store: RunStore) -> Path:
    """Write a self-contained report and machine-readable campaign list."""
    graph = store.load_graph()
    labels = GraphLabels(
        case_view=pl.REPORT_CASE_GRAPH,
        entity_view=pl.REPORT_ENTITY_GRAPH,
        evidence=pl.REPORT_EVIDENCE,
        family_names=pl.FAMILY_NAMES,
        tier_names=pl.REPORT_TIERS,
    )
    fragment = render_graph(graph, labels)
    template = (
        files("fakecollector.report")
        .joinpath("templates", "report.html.j2")
        .read_text(encoding="utf-8")
    )
    environment = Environment(autoescape=select_autoescape(default=True))
    text = environment.from_string(template).render(
        pl=pl, report=report_data(store, graph), graph=fragment
    )
    path = store.run_dir / "report.html"
    path.write_text(text, encoding="utf-8")
    (store.run_dir / "campaigns.json").write_text(
        json.dumps(
            [c.model_dump(mode="json") for c in graph.campaigns], ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    return path
