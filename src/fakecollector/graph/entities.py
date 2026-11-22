"""Entity extraction for the case graph.

Turns feature values (domains, IPs and similar identifiers) into graph entities and
case-to-entity links, dropping values on the stoplist.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Collection, Mapping
from ipaddress import ip_address, ip_network
from urllib.parse import urlsplit

from fakecollector.core.registry import FEATURES, FeatureSpec
from fakecollector.core.schemas import Entity, Feature
from fakecollector.extractors.brand_rules import brand_domains
from fakecollector.graph.config import EdgeConfig
from fakecollector.graph.stoplist import is_stopped_host, is_stopped_ip

logger = logging.getLogger(__name__)

type EntityLink = tuple[str, str, str]

_GRAPH_ENTITY_TYPES = {
    ("img.phash", None): "ImageGroup",
    ("img.pdq", None): "ImageGroup",
    ("infra.redirect_hop", "Host"): "RedirectHop",
    ("url.outlink_domain", "Domain"): "OutlinkDomain",
    ("ocr.domain", "Domain"): "OcrDomain",
}


def entity_type_for(name: str, spec: FeatureSpec) -> str | None:
    """Resolve graph types for image keys and keep outlinks and redirects distinct."""
    return _GRAPH_ENTITY_TYPES.get((name, spec.entity_type), spec.entity_type)


def _default_stopped(value: str, entity_type: str | None) -> bool:
    if entity_type == "IP":
        return is_stopped_ip(value)
    if entity_type not in {"Host", "Domain", "Endpoint"}:
        return False
    # Endpoint keys can have an HTTP method prefix and a port before the path.
    parts = value.split(maxsplit=1)
    address = parts[-1] if parts else ""
    try:
        host = urlsplit(address if "://" in address or address.startswith("//") else f"//{address}")
        return is_stopped_host(host.hostname or "")
    except ValueError:
        return False


def build_entities(
    features: Collection[Feature],
    registry: Mapping[str, FeatureSpec] = FEATURES,
    stoplist: Collection[str] = (),
    cfg: EdgeConfig | None = None,
    *,
    case_ids: Collection[str] = (),
) -> tuple[list[Entity], list[EntityLink]]:
    """Build typed entities and distinct case-to-entity links with artifact provenance.

    Campaign keys can identify a large share of the batch, so only supplied and
    enabled default stop-lists can stop them. The document-frequency cap still
    applies to other tiers and to campaign set members such as shared library
    hashes. Every entity retains its case count for display.
    """
    cfg = cfg or EdgeConfig()
    n = len(set(case_ids).union(feature.case_id for feature in features))
    definitions: dict[str, tuple[str, FeatureSpec, str, str]] = {}
    cases_by_entity: dict[str, set[str]] = defaultdict(set)
    fractions: dict[str, float] = {}
    families: dict[str, str] = {}
    # Document frequency is a share of the cases that could carry the entity at all: a corpus
    # of bare screenshots has no HAR, so it must not make a shared landing kit look rare.
    cases_by_family: dict[str, set[str]] = defaultdict(set)
    links: set[EntityLink] = set()
    unknown: set[str] = set()
    for feature in features:
        spec = registry.get(feature.name)
        if spec is None:
            unknown.add(feature.name)
            continue
        cases_by_family[spec.family].add(feature.case_id)
        entity_type = entity_type_for(feature.name, spec)
        if spec.kind not in {"key", "set"} or entity_type is None or not feature.value:
            continue
        entity_id = f"{entity_type}:{feature.value}"
        if entity_id not in definitions or feature.name < definitions[entity_id][0]:
            definitions[entity_id] = feature.name, spec, entity_type, feature.value
        cases_by_entity[entity_id].add(feature.case_id)
        fraction = spec.max_df
        fractions[entity_id] = min(fraction, fractions.get(entity_id, fraction))
        families.setdefault(entity_id, spec.family)
        links.add((feature.case_id, entity_id, feature.artifact_id))

    for name in sorted(unknown):
        logger.warning("Ignoring unknown feature %s", name)

    exceptions = set(stoplist)
    networks = []
    for item in exceptions:
        if "/" in item:
            try:
                networks.append(ip_network(item, strict=False))
            except ValueError:
                continue

    entities: list[Entity] = []
    for entity_id, (_, spec, entity_type, value) in sorted(definitions.items()):
        df = len(cases_by_entity[entity_id])
        comparable = min(n, len(cases_by_family[families[entity_id]])) or n
        campaign_key = spec.tier == "campaign" and spec.kind == "key"
        stopped = (
            entity_id in exceptions
            or value in exceptions
            or (not campaign_key and df > max(cfg.max_df_min, fractions[entity_id] * comparable))
            or (cfg.use_default_stoplist and _default_stopped(value, spec.entity_type))
        )
        # A well-known brand or news portal read from pixels is the imitated site, not the
        # scam's host (fake "gazeta.pl" articles): it says nothing about the campaign.
        if entity_type == "OcrDomain" and value in brand_domains():
            stopped = True
        if entity_type == "IP" and networks and not stopped:
            try:
                address = ip_address(value)
            except ValueError:
                logger.warning("Ignoring CIDR matching for an invalid IP feature")
            else:
                stopped = any(address in network for network in networks)
        entities.append(
            Entity(
                id=entity_id,
                type=entity_type,
                value=value,
                tier=spec.tier,
                df=df,
                stop=stopped,
            )
        )
    return entities, sorted(links)
