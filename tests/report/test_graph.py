from fakecollector.core.schemas import Edge, Entity, Evidence
from fakecollector.graph.analyze import Analysis
from fakecollector.report.graph import (
    GraphLabels,
    build_case_graph,
    build_entity_graph,
    render_graph,
)


def _analysis() -> Analysis:
    return Analysis(
        case_ids=["case-a", "case-b", "case-c"],
        entities=[
            Entity(
                id="Domain:site.example", type="Domain", value="site.example", tier="operator", df=2
            ),
            Entity(id="Host:shared", type="Host", value="shared", tier="toolkit", df=2, stop=True),
        ],
        links=[("case-a", "Domain:site.example", "a"), ("case-b", "Domain:site.example", "b")],
        edges=[
            Edge(
                src="case-a",
                dst="case-b",
                score=0.9,
                operator_link=False,
                signals={"ids": 0.8, "text": 0.5, "image": 0.7},
                comparable=["ids", "text"],
                evidence=[
                    Evidence(
                        family="ids",
                        tier="campaign",
                        kind="ids.kit_landing",
                        value="x",
                        detail="same trace",
                        weight=0.8,
                    )
                ],
            )
        ],
        campaigns=[],
        operators={},
        toolkits={},
    )


def test_case_graph_keeps_independent_comparable_families() -> None:
    graph = build_case_graph(_analysis())
    assert {node.label for node in graph.nodes} == {"case-a", "case-b", "case-c"}
    assert {edge.family for edge in graph.edges} == {"ids", "text"}
    assert len(graph.edges) == 2
    assert next(edge for edge in graph.edges if edge.family == "ids").evidence == ["same trace"]


def test_entity_graph_uses_shared_non_stopped_entities() -> None:
    graph = build_entity_graph(_analysis())
    # case-c shares no entity, so the entity view leaves it out (it is in the case view)
    assert {node.label for node in graph.nodes} == {"case-a", "case-b", "site[.]example"}
    assert "site[.]example" in {node.label for node in graph.nodes}
    assert len(graph.edges) == 2


def test_graph_defangs_every_dot_in_a_hostname() -> None:
    analysis = _analysis()
    analysis.entities[0].value = "sub.site.example"
    assert "sub[.]site[.]example" in {node.label for node in build_entity_graph(analysis).nodes}


def test_long_graph_labels_have_full_defanged_tooltip() -> None:
    analysis = _analysis()
    analysis.entities[0].value = "long-subdomain-" + "x" * 48 + ".example"
    node = next(node for node in build_entity_graph(analysis).nodes if node.kind == "entity")
    assert len(node.label) <= 32
    assert node.label.endswith("…")
    assert node.full_label.endswith("[.]example")


def test_render_graph_escapes_untrusted_script_content() -> None:
    analysis = _analysis()
    analysis.edges[0].evidence[0].detail = "</script><script>alert(1)</script>"
    labels = GraphLabels(case_view="Cases", entity_view="Entities", evidence="Evidence")
    rendered = render_graph(analysis, labels)
    assert "</script><script>alert(1)</script>" not in rendered
    assert "\\u003c/script\\u003e" in rendered
    assert "https://" not in rendered
    assert "site.example" not in rendered


def test_case_nodes_carry_campaign_fill_link_state_and_focus() -> None:
    from fakecollector.core.schemas import Campaign
    from fakecollector.report.graph import CAMPAIGN_FILLS, SINGLETON_FILL

    analysis = _analysis().model_copy(
        update={
            "campaigns": [
                Campaign(
                    id="C1",
                    operator_id=None,
                    case_ids=["case-a", "case-b"],
                    label="A",
                    traits=[],
                    cohesion=0.9,
                ),
                Campaign(
                    id="C2",
                    operator_id=None,
                    case_ids=["case-c"],
                    label="C",
                    traits=[],
                    cohesion=1.0,
                ),
            ]
        }
    )
    nodes = {n.label: n for n in build_case_graph(analysis, focus="case-a").nodes}
    assert nodes["case-a"].fill == nodes["case-b"].fill == CAMPAIGN_FILLS[0]
    assert nodes["case-c"].fill == SINGLETON_FILL
    assert nodes["case-a"].linked and not nodes["case-c"].linked
    assert nodes["case-a"].focus and not nodes["case-b"].focus


def test_entity_labels_shorten_hashes_but_keep_the_full_value() -> None:
    digest = "ab" * 32
    analysis = _analysis().model_copy(
        update={
            "entities": [
                Entity(id=f"Asset:{digest}", type="Asset", value=digest, tier="campaign", df=2)
            ],
            "links": [("case-a", f"Asset:{digest}", "a"), ("case-b", f"Asset:{digest}", "b")],
        }
    )
    node = next(n for n in build_entity_graph(analysis).nodes if n.kind == "entity")
    assert node.label.startswith("ababababab…") and len(node.label) < 20
    assert digest in node.full_label
    assert node.df == 2


def test_compact_render_drops_the_duplicate_family_filter() -> None:
    labels = GraphLabels(case_view="Z", entity_view="E", evidence="D")
    full = render_graph(_analysis(), labels)
    compact = render_graph(_analysis(), labels, focus="case-a", compact=True)
    assert 'class="fc-family"' in full
    assert 'class="fc-family"' not in compact
    assert "const focused = true" in compact
