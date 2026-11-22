"""Campaign clustering over the case graph.

Groups cases into connected components above the campaign threshold, then derives
cohesion, operator and toolkit attribution, and human-readable campaign labels.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from collections.abc import Collection, Mapping
from hashlib import sha256
from math import log1p
from statistics import mean

import networkx as nx

from fakecollector.core.schemas import Campaign, Edge, Entity, Feature, Tier
from fakecollector.core.text import tokens
from fakecollector.graph.config import EdgeConfig
from fakecollector.graph.entities import EntityLink
from fakecollector.graph.signals import evidence_order

logger = logging.getLogger(__name__)

_LABEL_STOPWORDS = frozenset(
    {
        "aby",
        "albo",
        "ale",
        "oraz",
        "bez",
        "dla",
        "gdy",
        "jest",
        "jaki",
        "jako",
        "jego",
        "jej",
        "już",
        "lub",
        "między",
        "można",
        "nawet",
        "nie",
        "po",
        "pod",
        "przed",
        "się",
        "przez",
        "także",
        "ten",
        "tego",
        "tej",
        "to",
        "tylko",
        "tym",
        "więcej",
        "wszystko",
        "został",
        "została",
        "którzy",
        "który",
        "które",
        "gdyby",
        "the",
        "and",
        "are",
        "for",
        "from",
        "has",
        "have",
        "into",
        "its",
        "not",
        "that",
        "their",
        "this",
        "was",
        "were",
        "with",
        "you",
        "your",
        "sponsorowane",
        "sponsored",
        "polub",
        "obserwuj",
        "zobacz",
        "udostępnij",
        "komentarze",
        "komentarzy",
        "reklama",
        "advertisement",
        "follow",
        "like",
        "share",
    }
)
_OCR_CHROME = frozenset(
    {
        "sponsorowane",
        "sponsored",
        "polub",
        "obserwuj",
        "follow",
        "advertisement",
    }
)


def cluster(
    case_ids: Collection[str],
    edges: Collection[Edge],
    cfg: EdgeConfig,
    operators: Mapping[str, str] | None = None,
) -> list[Campaign]:
    """Group cases into connected components at or above the campaign threshold.

    Components are transitive, so a single erroneous edge at or above the threshold can join
    two campaigns. The campaign gate and tier slots keep spurious edges out. Two guards
    partition a component instead of keeping it whole: the size and cohesion test, and a
    component whose members belong to more than one known operator (a campaign has at most
    one operator, ADR 0004), which is how a multi-story capture such as a cloaked case
    chains two campaigns.
    """
    ids = set(case_ids)
    strong = sorted(
        (
            e
            for e in edges
            if e.score >= cfg.tau and e.src in ids and e.dst in ids and e.src != e.dst
        ),
        key=lambda e: (e.src, e.dst, e.score),
    )
    graph = nx.Graph()
    graph.add_nodes_from(sorted(ids))
    graph.add_edges_from((edge.src, edge.dst) for edge in strong)
    groups = [sorted(component) for component in nx.connected_components(graph)]
    campaigns: list[Campaign] = []
    for members, internal in zip(groups, _internal_edges(groups, strong), strict=True):
        cohesion = _cohesion(internal)
        if (
            len(members) > max(cfg.giant_min_size, cfg.giant_fraction * len(ids))
            and cohesion < cfg.giant_cohesion
        ):
            # Keep the existing Leiden/Louvain guard, scoped to this component so
            # unrelated edges cannot affect the partitioner's modularity objective.
            split = _partition(members, internal, cfg, 2 * cfg.resolution)
            campaigns.extend(
                _campaign(group, group_edges, _cohesion(group_edges), ["giant_split"])
                for group, group_edges in zip(split, _internal_edges(split, internal), strict=True)
            )
        elif operators is not None and len({operators[m] for m in members if m in operators}) > 1:
            # Partition only inside this component, so the modularity objective sees the
            # conflicting sub-groups and nothing else in the corpus.
            split = _partition(members, internal, cfg, cfg.resolution)
            campaigns.extend(
                _campaign(group, group_edges, _cohesion(group_edges), ["operator_split"])
                for group, group_edges in zip(split, _internal_edges(split, internal), strict=True)
            )
        else:
            campaigns.append(_campaign(members, internal, cohesion, []))
    return sorted(campaigns, key=lambda campaign: campaign.case_ids[0])


def _partition(
    case_ids: list[str], edges: list[Edge], cfg: EdgeConfig, resolution: float
) -> list[list[str]]:
    if not edges:
        return [[case] for case in case_ids]

    connected = {case for edge in edges for case in (edge.src, edge.dst)}
    nodes = [case for case in case_ids if case in connected]
    isolates = [[case] for case in case_ids if case not in connected]
    if cfg.cluster_algo == "leiden":
        try:
            import igraph
            import leidenalg
        except ImportError:
            logger.warning("Leiden dependencies unavailable; using Louvain")
        else:
            index = {case: i for i, case in enumerate(nodes)}
            graph = igraph.Graph(n=len(nodes), edges=[(index[e.src], index[e.dst]) for e in edges])
            graph.es["score"] = [edge.score for edge in edges]
            partition = leidenalg.find_partition(
                graph,
                leidenalg.RBConfigurationVertexPartition,
                weights="score",
                resolution_parameter=resolution,
                seed=cfg.seed,
            )
            return sorted(isolates + [sorted(nodes[i] for i in group) for group in partition])

    graph_nx = nx.Graph()
    graph_nx.add_nodes_from(nodes)
    graph_nx.add_weighted_edges_from((e.src, e.dst, e.score) for e in edges)
    communities = nx.community.louvain_communities(graph_nx, resolution=resolution, seed=cfg.seed)
    return sorted(isolates + [sorted(group) for group in communities])


def _internal_edges(groups: list[list[str]], edges: list[Edge]) -> list[list[Edge]]:
    membership = {case: i for i, group in enumerate(groups) for case in group}
    internal: list[list[Edge]] = [[] for _ in groups]
    for edge in edges:
        if membership[edge.src] == membership[edge.dst]:
            internal[membership[edge.src]].append(edge)
    return internal


def _cohesion(edges: list[Edge]) -> float:
    return mean(edge.score for edge in edges) if edges else 1.0


def _campaign(members: list[str], edges: list[Edge], cohesion: float, flags: list[str]) -> Campaign:
    top = min((item for edge in edges for item in edge.evidence), default=None, key=evidence_order)
    return Campaign(
        id=f"C-{_sha8(members[0])}",
        operator_id=None,
        case_ids=members,
        label=top.detail if top is not None else members[0],
        traits=[],
        cohesion=cohesion,
        flags=flags,
    )


def _sha8(value: str) -> str:
    return sha256(value.encode()).hexdigest()[:8]


def operators(
    case_ids: Collection[str], entities: Collection[Entity], links: Collection[EntityLink]
) -> dict[str, str]:
    """Connect cases transitively through shared, non-stopped operator entities."""
    groups = _tier_groups(case_ids, entities, links, "operator")
    union = nx.utils.UnionFind()
    for cases in groups.values():
        if len(cases) > 1:
            union.union(*sorted(cases))
    by_case: dict[str, str] = {}
    for group in union.to_sets():
        operator_id = f"O-{_sha8(min(group))}"
        by_case.update((case, operator_id) for case in group)
    return dict(sorted(by_case.items()))


def toolkits(
    case_ids: Collection[str], entities: Collection[Entity], links: Collection[EntityLink]
) -> dict[str, list[str]]:
    """Return each case's non-stopped toolkit entities, including overlaps."""
    by_case: dict[str, list[str]] = {case: [] for case in sorted(set(case_ids))}
    for entity_id, cases in sorted(_tier_groups(case_ids, entities, links, "toolkit").items()):
        for case in cases:
            by_case[case].append(entity_id)
    return by_case


def _tier_groups(
    case_ids: Collection[str],
    entities: Collection[Entity],
    links: Collection[EntityLink],
    tier: Tier,
) -> dict[str, set[str]]:
    ids = set(case_ids)
    active = {entity.id for entity in entities if entity.tier == tier and not entity.stop}
    groups: dict[str, set[str]] = defaultdict(set)
    for case, entity_id, _ in links:
        if case in ids and entity_id in active:
            groups[entity_id].add(case)
    return groups


def attach_operators(campaigns: Collection[Campaign], operators: Mapping[str, str]) -> None:
    """Set each campaign's unique known operator and flag conflicting memberships."""
    for campaign in campaigns:
        known = {operators[case] for case in campaign.case_ids if case in operators}
        campaign.operator_id = next(iter(known)) if len(known) == 1 else None
        if len(known) > 1 and "mixed_operator" not in campaign.flags:
            campaign.flags.append("mixed_operator")
        elif len(known) <= 1 and "mixed_operator" in campaign.flags:
            campaign.flags.remove("mixed_operator")


def attach_toolkits(campaigns: Collection[Campaign], toolkits: Mapping[str, list[str]]) -> None:
    """Collect the active toolkit entities observed across each campaign's members."""
    for campaign in campaigns:
        campaign.toolkits = sorted(
            {toolkit for case in campaign.case_ids for toolkit in toolkits[case]}
        )


def label_campaigns(campaigns: Collection[Campaign], features: Collection[Feature]) -> None:
    """Label campaigns from their narrative or class-based TF-IDF terms."""
    campaign_by_case = {case: campaign.id for campaign in campaigns for case in campaign.case_ids}
    headlines: dict[tuple[str, int], Counter[str]] = defaultdict(Counter)
    terms: dict[str, Counter[str]] = defaultdict(Counter)
    observed: set[tuple[str, str, str, str]] = set()
    ocr_sources = {(f.case_id, f.artifact_id) for f in features if f.name == "text.ocr"}
    ocr_titles = {(f.case_id, f.artifact_id) for f in features if f.name == "ocr.headline"}
    for feature in features:
        case, name, value = feature.case_id, feature.name, feature.value
        campaign_id = campaign_by_case.get(case)
        key = (case, name, value, feature.locator if name == "text.headline_tpl" else "")
        if not value or campaign_id is None or key in observed:
            continue
        if name == "text.headline_tpl":
            source = (case, feature.artifact_id)
            is_page_title = feature.locator == "from:html.title" or (
                not feature.locator and source not in ocr_sources
            )
            is_ocr_title = (
                feature.locator == "from:text.ocr"
                and source in ocr_titles
                and not (_OCR_CHROME & set(tokens(value)))
            )
            if is_page_title or is_ocr_title:
                headlines[campaign_id, 0 if is_page_title else 1][value] += 1
        elif name in {"text.raw", "text.ocr", "text.asr"}:
            terms[campaign_id].update(
                term
                for term in tokens(value)
                if len(term) >= 3 and term.isalpha() and term not in _LABEL_STOPWORDS
            )
        else:
            continue
        observed.add(key)

    frequency: Counter[str] = Counter()
    for class_terms in terms.values():
        frequency.update(class_terms)
    average_length = frequency.total() / max(1, len(terms))
    for campaign in campaigns:
        headline = _most_common(headlines[campaign.id, 0]) or _most_common(
            headlines[campaign.id, 1]
        )
        if headline:
            campaign.label = headline.replace("{PERSON}", "[osoba]")
        elif counts := terms.get(campaign.id):
            # The class term-frequency denominator is constant within each campaign.
            ordered = sorted(
                (-count * log1p(average_length / frequency[term]), term)
                for term, count in counts.items()
            )
            campaign.label = ", ".join(term for _, term in ordered[:3])


def _most_common(counts: Counter[str]) -> str | None:
    return min(counts, key=lambda value: (-counts[value], value), default=None)
