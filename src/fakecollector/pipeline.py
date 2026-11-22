"""Orchestrate extraction and analysis for a persisted run."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import re
import tempfile
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlsplit

from fakecollector.config import get_settings
from fakecollector.core.extractor import Extractor
from fakecollector.core.schemas import Artifact, Assignment, Case, Feature
from fakecollector.enrich import ENRICH_EXTRACTOR, ENRICH_VERSION, enrich_case
from fakecollector.extractors.ad_library import AdLibraryExtractor
from fakecollector.extractors.asset import AssetExtractor
from fakecollector.extractors.brand_rules import BrandRulesExtractor
from fakecollector.extractors.derived import DerivedMediaExtractor, expand_derived
from fakecollector.extractors.face import FaceExtractor
from fakecollector.extractors.har_ids import IdsExtractor, ids_from_url
from fakecollector.extractors.html_page import HtmlPageExtractor
from fakecollector.extractors.image_embed import SiglipExtractor
from fakecollector.extractors.image_hash import ImageHashExtractor
from fakecollector.extractors.infra import RequestGraphExtractor, registrable_domain
from fakecollector.extractors.infra_meta import InfraMetaExtractor
from fakecollector.extractors.ocr import OcrExtractor
from fakecollector.extractors.pdf_text import PdfTextExtractor
from fakecollector.extractors.person_text import PersonMentionExtractor
from fakecollector.extractors.source_meta import SourceMetaExtractor
from fakecollector.extractors.template import TemplateExtractor
from fakecollector.extractors.text import TextExtractor
from fakecollector.extractors.video import VideoExtractor
from fakecollector.graph.analyze import Analysis
from fakecollector.graph.analyze import analyze as analyze_graph
from fakecollector.graph.assign import assign, cluster_new
from fakecollector.graph.config import EdgeConfig
from fakecollector.graph.coverage import INSUFFICIENT_DATA, annotate_coverage
from fakecollector.graph.profile import fill_traits
from fakecollector.ingest.casefolder import load_corpus
from fakecollector.ingest.normalize import canonical_url, url_schema
from fakecollector.store import FeatureCache, RunStore

logger = logging.getLogger(__name__)

_BARE_DOMAIN = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}(?:/\S*)?", re.I)


_FILE_SUFFIXES = frozenset(
    {"py", "sh", "md", "rs", "zip", "mov", "txt", "csv", "json", "html", "htm", "mhtml"}
    | {"har", "pdf", "png", "jpg", "jpeg", "webp", "gif", "mp4", "webm"}
)


_TEXT_HINT_WORDS = 3
_MAX_PLAIN_TEXT = 20_000


def _path_exists(path: Path) -> bool:
    """`Path.exists` that treats an over-long or invalid name (pasted text) as missing."""
    try:
        return path.exists()
    except (OSError, ValueError):
        return False


def _read_plain_text(path: Path) -> str:
    """Up to `_MAX_PLAIN_TEXT` characters of a text file, decoded leniently."""
    try:
        with path.open("rb") as handle:
            data = handle.read(_MAX_PLAIN_TEXT * 4)
    except OSError:
        return ""
    return data.decode("utf-8-sig", errors="replace").strip()[:_MAX_PLAIN_TEXT]


def _bare_url(value: str) -> str | None:
    """`https://<value>` for a typed bare domain ("example.com/a"), else None.

    A host ending in a file extension ("raport.pdf", "zrzut.png") is a mistyped local path
    and is still reported as missing instead of becoming a URL.
    """
    value = value.strip()
    if not _BARE_DOMAIN.fullmatch(value):
        return None
    if value.split("/", 1)[0].rsplit(".", 1)[-1].lower() in _FILE_SUFFIXES:
        return None
    return f"https://{value}"


def ingest(paths: list[Path], store: RunStore) -> None:
    """Load case folders without fetching or executing their contents."""
    cases, artifacts = [], []
    used: set[str] = set()
    for path in paths:
        if not path.exists():
            logger.warning("Input does not exist: %s", path)
            continue
        corpus = (path.name or "input").encode("utf-8", "backslashreplace").decode("utf-8")
        base = corpus
        suffix = 2
        while corpus in used:
            corpus = f"{base}-{suffix}"
            suffix += 1
        used.add(corpus)
        loaded_cases, loaded_artifacts = load_corpus(path, corpus)
        cases.extend(loaded_cases)
        artifacts.extend(loaded_artifacts)
    if not used:
        raise FileNotFoundError("No input paths exist")
    store.invalidate_results()
    store.write_cases(cases, artifacts)


def default_extractors(profile: Literal["fast", "full"] = "fast") -> list[Extractor]:
    """Create the available CPU extractors in deterministic stage order."""
    return [
        IdsExtractor(),
        AssetExtractor(),
        HtmlPageExtractor(),
        RequestGraphExtractor(),
        TemplateExtractor(),
        InfraMetaExtractor(),
        BrandRulesExtractor(),
        PdfTextExtractor(),
        cast(Extractor, ImageHashExtractor()),
        AdLibraryExtractor(),
        SourceMetaExtractor(),
        VideoExtractor(),
        OcrExtractor(),  # before SigLIP: its masthead brands confirm logo matches
        cast(Extractor, SiglipExtractor()),
        cast(Extractor, FaceExtractor()),
        TextExtractor(enable_embeddings=profile == "full"),
        PersonMentionExtractor(),
    ]


def extract(
    store: RunStore,
    profile: Literal["fast", "full"] = "fast",
    *,
    cache: FeatureCache | None = None,
    extractors: list[Extractor] | None = None,
) -> None:
    """Run extractors, skipping failed artifacts and preserving per-case prior features."""
    artifacts = store.artifacts()
    selected = extractors if extractors is not None else default_extractors(profile)
    if extractors is None:
        additions = expand_derived(artifacts, DerivedMediaExtractor(extractors=[]))
        if additions:
            artifacts.extend(additions)
            store.write_cases(store.cases(), artifacts)
    by_case: dict[str, list[Feature]] = defaultdict(list)
    refreshed: list[Feature] = []
    for feature in store.features_from_extractor("input"):
        by_case[feature.case_id].append(feature)
    for extractor in sorted(selected, key=lambda item: item.stage):
        if extractor.requires == "ml" and (
            profile == "fast" or importlib.util.find_spec("torch") is None
        ):
            logger.warning(
                "Skipping extractor %s: ML profile or dependencies unavailable", extractor.name
            )
            store.add_features([], extractor.name, extractor.version)
            continue
        results: list[Feature] = []
        if extractor.requires == "ml" or extractor.name == "text":
            supported = [artifact for artifact in artifacts if extractor.supports(artifact)]
            if extractor.name == "text":
                seen_cases: set[str] = set()
                representatives = []
                for artifact in supported:
                    if artifact.case_id not in seen_cases:
                        representatives.append(artifact)
                        seen_cases.add(artifact.case_id)
                supported = representatives
            try:
                batches = extractor.extract_batch(
                    supported, [by_case[artifact.case_id] for artifact in supported]
                )
                if len(batches) != len(supported):
                    raise ValueError("Extractor returned the wrong number of batch results")
                results = [feature for batch in batches for feature in batch]
            except Exception:
                logger.exception("Batch extractor %s failed; retrying artifacts", extractor.name)
                for artifact in supported:
                    try:
                        results.extend(extractor.extract(artifact, by_case[artifact.case_id]))
                    except Exception:
                        logger.exception(
                            "Extractor %s failed for %s", extractor.name, artifact.path
                        )
            for feature in results:
                by_case[feature.case_id].append(feature)
            refreshed.extend(results)
            store.add_features(results, extractor.name, extractor.version)
            continue
        seen: set[str] = set()
        for artifact in artifacts:
            if extractor.name == "text" and artifact.case_id in seen:
                continue
            try:
                if not extractor.supports(artifact):
                    continue
                seen.add(artifact.case_id)
                use_cache = (
                    cache is not None
                    and extractor.stage == 1
                    and (getattr(extractor, "cacheable", False) or extractor.name == "html_page")
                )
                digest = artifact.meta.get("sha256")
                if use_cache and not digest:
                    digest = hashlib.sha256(artifact.path.read_bytes()).hexdigest()
                cached = (
                    cache.get(
                        digest,
                        extractor.name,
                        extractor.version,
                        case_id=artifact.case_id,
                        artifact_id=artifact.id,
                    )
                    if use_cache and digest and cache is not None
                    else None
                )
                if cached is None:
                    found = extractor.extract(artifact, by_case[artifact.case_id])
                    if use_cache and digest and cache is not None:
                        try:
                            cache.put(digest, extractor.name, extractor.version, found)
                        except OSError:
                            logger.warning("Could not write feature cache", exc_info=True)
                else:
                    found = cached
                results.extend(found)
            except Exception:
                logger.exception("Extractor %s failed for %s", extractor.name, artifact.path)
        for feature in results:
            by_case[feature.case_id].append(feature)
        refreshed.extend(results)
        store.add_features(results, extractor.name, extractor.version)
    if get_settings().allow_enrich:
        # Opt-in passive metadata (DNS, ASN, RDAP, CT) for each case's domains and non-CDN
        # IPs; responses are cached on disk, so a re-run costs no network.
        enriched: list[Feature] = []
        for case_id, fs in sorted(by_case.items()):
            try:
                enriched.extend(enrich_case(case_id, fs))
            except Exception:
                logger.warning("Enrichment failed for case %s", case_id, exc_info=True)
        store.add_features(enriched, ENRICH_EXTRACTOR, ENRICH_VERSION)
    else:
        store.add_features([], ENRICH_EXTRACTOR, ENRICH_VERSION)

    # Features committed through assignment have no per-extractor provenance. Remove only
    # records actually regenerated above: URL-only input and unavailable modalities must survive.
    regenerated = Counter(feature.model_dump_json() for feature in refreshed)
    remaining = []
    for feature in store.features_from_extractor("assignment"):
        key = feature.model_dump_json()
        if regenerated[key]:
            regenerated[key] -= 1
        else:
            remaining.append(feature)
    store.add_features(remaining, "assignment", 1)


def analyze(store: RunStore, cfg: EdgeConfig | None = None) -> Analysis:
    """Build and persist a graph from the run's extracted features."""
    result = fill_traits(
        analyze_graph(store.all_features(), [case.id for case in store.cases()], cfg)
    )
    store.save_graph(result)
    return result


def assign_new(
    paths_or_urls: Sequence[str | Path],
    store: RunStore,
    commit: bool = False,
    *,
    features_out: list[Feature] | None = None,
    artifacts_out: list[Artifact] | None = None,
) -> list[Assignment]:
    """Assign new inputs to fixed campaigns, optionally adding them to the run.

    `features_out` / `artifacts_out`, when given, receive the new cases' features and
    artifacts (what was recognised, for the verdict). Artifact paths inside the temporary
    folder are valid only until this function returns.
    """
    base = store.load_graph()
    base_features = store.all_features()
    metadata_path = store.run_dir / "run.json"
    metadata = (
        json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    )
    profile: Literal["fast", "full"] = "full" if metadata.get("profile") == "full" else "fast"
    cfg = EdgeConfig(seed=metadata.get("seed", 0))
    old_cases, old_artifacts = store.cases(), store.artifacts()
    used = {case.id for case in old_cases}
    with tempfile.TemporaryDirectory(prefix="fakecollector-") as directory:
        temporary = Path(directory)
        cases: list[Case] = []
        artifacts: list[Artifact] = []
        url_features: list[Feature] = []
        for index, raw in enumerate(paths_or_urls):
            value = str(raw)
            if isinstance(raw, str) and not _path_exists(Path(value)) and (url := _bare_url(value)):
                value = url
            try:
                parsed = urlsplit(value)
            except ValueError:
                logger.warning("Invalid input skipped: %s", value)
                continue
            path = Path(value)
            is_url = parsed.scheme in {"http", "https"} and bool(parsed.hostname)
            # Pasted text (a headline, an ad description) is a hint too: several words are
            # never a mistyped local path, even with a full stop or a slash inside.
            is_hint = (
                not is_url
                and isinstance(raw, str)
                and not _path_exists(path)
                and (
                    len(value.split()) >= _TEXT_HINT_WORDS
                    or ("/" not in value and "\\" not in value and not path.suffix)
                )
            )
            if is_url or is_hint:
                digest = hashlib.sha256(value.encode()).hexdigest()
                path = temporary / f"input-{index}.txt"
                path.write_text(value, encoding="utf-8")
                case = Case(
                    id=f"U:{digest[:8]}",
                    corpus="upload",
                    path=path,
                    landing_urls=[canonical_url(value)] if is_url else [],
                )
                artifact = Artifact(
                    id=digest[:16],
                    case_id=case.id,
                    kind="url" if is_url else "text",
                    role="other",
                    path=path,
                    size=len(value.encode()),
                    meta={"sha256": digest},
                )
                raw_cases, raw_artifacts = [case], [artifact]
            else:
                if not _path_exists(path):
                    logger.warning("Input does not exist: %s", path)
                    continue
                raw_cases, raw_artifacts = load_corpus(path, "upload")
            mapping: dict[str, str] = {}
            for case in raw_cases:
                original = case.id
                case_artifacts = [
                    artifact for artifact in raw_artifacts if artifact.case_id == original
                ]
                hashes = sorted(
                    artifact.meta.get("sha256", artifact.id) for artifact in case_artifacts
                )
                digest = (
                    hashes[0][:8]
                    if len(hashes) == 1
                    else hashlib.sha256("\0".join(hashes or [original]).encode()).hexdigest()[:8]
                )
                case.id = f"U:{digest}"
                counter = 2
                while case.id in used:
                    case.id = f"U:{digest}-{counter}"
                    counter += 1
                used.add(case.id)
                mapping[original] = case.id
                cases.append(case)
            for artifact in raw_artifacts:
                artifact.case_id = mapping[artifact.case_id]
                artifacts.append(artifact)
                if artifact.kind == "url":
                    keys = ids_from_url(value)
                    keys["url.domain"] = {registrable_domain(parsed.hostname or "")}
                    keys["url.schema"] = {url_schema(value)}
                    for name, values in keys.items():
                        for item in sorted(values):
                            if item:
                                url_features.append(
                                    Feature(
                                        case_id=artifact.case_id,
                                        artifact_id=artifact.id,
                                        name=name,
                                        value=item,
                                        locator="url",
                                    )
                                )
                elif artifact.kind == "text" and not is_hint:
                    # A .txt description (loose or opis.txt in a folder) is read like a
                    # pasted text: the same text family as OCR and page text.
                    if text := _read_plain_text(artifact.path):
                        url_features.append(
                            Feature(
                                case_id=artifact.case_id,
                                artifact_id=artifact.id,
                                name="text.raw",
                                value=text,
                                locator="input",
                            )
                        )
                elif is_hint:
                    url_features.append(
                        Feature(
                            case_id=artifact.case_id,
                            artifact_id=artifact.id,
                            name="text.raw",
                            value=value,
                            locator="input",
                        )
                    )
        new_store = RunStore(temporary / "run")
        new_store.write_cases(cases, artifacts)
        new_store.add_features(url_features, "input", 1)
        extract(new_store, profile, cache=FeatureCache(get_settings().feature_cache))
        artifacts = new_store.artifacts()
        new_features = new_store.all_features()
        assignments = assign(
            new_features, base, base_features, cfg, new_case_ids=[c.id for c in cases]
        )
        assignments = annotate_coverage(assignments, new_features, base_features)
        if features_out is not None:
            features_out.extend(new_features)
        if artifacts_out is not None:
            artifacts_out.extend(artifacts)
        for case in cases:
            flagged = any(
                a.case_id == case.id and INSUFFICIENT_DATA in a.flags for a in assignments
            )
            if flagged and INSUFFICIENT_DATA not in case.flags:
                case.flags.append(INSUFFICIENT_DATA)
        if commit and cases:
            by_case_id = {case.id: case for case in cases}
            for assignment in assignments:
                if assignment.duplicate_of is not None:
                    by_case_id[assignment.case_id].duplicate_of = assignment.duplicate_of
            for artifact in artifacts:
                if artifact.path.is_relative_to(temporary):
                    target = store.run_dir / "inputs" / f"{artifact.id}.txt"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(artifact.path.read_bytes())
                    artifact.path = target
                    next(case for case in cases if case.id == artifact.case_id).path = target
            store.write_cases([*old_cases, *cases], [*old_artifacts, *artifacts])
            prior_assigned = store.features_from_extractor("assignment")
            store.add_features([*prior_assigned, *new_features], "assignment", 1)
            combined = analyze_graph(
                [*base_features, *new_features], [case.id for case in [*old_cases, *cases]], cfg
            )
            campaigns = [campaign.model_copy(deep=True) for campaign in base.campaigns]
            by_id = {campaign.id: campaign for campaign in campaigns}
            for assignment in assignments:
                if assignment.decision == "existing" and assignment.campaign_id in by_id:
                    by_id[assignment.campaign_id].case_ids.append(assignment.case_id)
            campaigns.extend(cluster_new(assignments, new_features, base, base_features, cfg))
            reviews = [item.case_id for item in assignments if item.decision == "review"]
            if reviews:
                campaigns.extend(analyze_graph([], reviews).campaigns)
            combined.campaigns = campaigns
            store.save_graph(fill_traits(combined))
            if metadata_path.exists():
                metadata["counts"] = {
                    "cases": len(store.cases()),
                    "artifacts": len(store.artifacts()),
                    "features": len(store.features()),
                    "campaigns": len(campaigns),
                }
                metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return assignments
