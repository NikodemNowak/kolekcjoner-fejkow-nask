from fakecollector.app.links import FAMILY_ORDER, linked_subgraph, neighbour_rows
from fakecollector.core.schemas import Campaign, Edge, Evidence
from fakecollector.graph.analyze import Analysis
from fakecollector.report.graph import build_case_graph


def _ev(family: str, detail: str, weight: float) -> Evidence:
    return Evidence(
        family=family, tier="campaign", kind="x", value="v", detail=detail, weight=weight
    )  # type: ignore[arg-type]


def _analysis() -> Analysis:
    edges = [
        Edge(
            src="T:a",
            dst="T:b",
            score=0.99,
            operator_link=True,
            signals={"ids": 0.97, "image": 0.9, "text": 0.8},
            comparable=["ids", "image", "text", "infra"],
            evidence=[_ev("ids", "ten sam landing", 0.97), _ev("image", "ten sam obraz", 0.9)],
        ),
        Edge(
            src="T:a",
            dst="T:c",
            score=0.6,
            operator_link=False,
            signals={"image": 0.6},
            comparable=["image"],
            evidence=[_ev("image", "podobny obraz", 0.6)],
        ),
        Edge(
            src="T:b",
            dst="T:c",
            score=0.5,
            operator_link=False,
            signals={"text": 0.5},
            comparable=["text"],
            evidence=[],
        ),
    ]
    camp = Campaign(
        id="C1",
        operator_id=None,
        case_ids=["T:a", "T:b"],
        label="Kampania X",
        traits=[],
        cohesion=0.99,
    )
    return Analysis(
        case_ids=["T:a", "T:b", "T:c"],
        entities=[],
        links=[],
        edges=edges,
        campaigns=[camp],
        operators={},
        toolkits={},
    )


def test_rows_list_every_linked_case_with_per_family_scores() -> None:
    rows = neighbour_rows(_analysis(), "T:a")
    assert [r.case_id for r in rows] == ["T:b", "T:c"]  # more families first
    b = rows[0]
    assert b.fired == ["ids", "image", "text"]
    assert b.per_family["ids"] == 0.97
    assert b.per_family["infra"] == 0.0  # comparable, did not fire
    assert b.per_family["asset"] is None  # not comparable: "brak danych", not 0
    assert b.campaign_label == "Kampania X"
    assert b.evidence[0] == "ten sam landing"
    assert set(b.per_family) == set(FAMILY_ORDER)


def test_filters_by_family_count_and_by_family() -> None:
    assert [r.case_id for r in neighbour_rows(_analysis(), "T:a", min_families=2)] == ["T:b"]
    assert [r.case_id for r in neighbour_rows(_analysis(), "T:a", families={"image"})] == [
        "T:b",
        "T:c",
    ]
    assert neighbour_rows(_analysis(), "T:a", families={"person"}) == []


def test_case_without_edges_has_no_rows() -> None:
    assert neighbour_rows(_analysis(), "T:zzz") == []


def test_multigraph_draws_one_edge_per_fired_family() -> None:
    analysis = _analysis()
    rows = neighbour_rows(analysis, "T:a")
    graph = build_case_graph(linked_subgraph(analysis, "T:a", rows))
    assert len(graph.edges) == 4
    assert sorted(edge.family for edge in graph.edges) == ["ids", "image", "image", "text"]


def test_signal_outside_comparable_is_no_data_and_not_drawn() -> None:
    edge = Edge(
        src="T:a",
        dst="T:d",
        score=0.7,
        operator_link=False,
        signals={"image": 0.7, "text": 0.4},
        comparable=["image"],
        evidence=[],
    )
    graph = _analysis()
    graph.edges.append(edge)
    [row] = [r for r in neighbour_rows(graph, "T:a") if r.case_id == "T:d"]
    assert row.per_family["text"] is None  # in signals, not comparable -> "brak danych"
    assert row.fired == ["image"]
    assert "T:d" not in {r.case_id for r in neighbour_rows(graph, "T:a", families={"text"})}
    displayed = build_case_graph(linked_subgraph(graph, "T:a", [row]))
    assert [edge.family for edge in displayed.edges] == ["image"]


def test_linked_subgraph_contains_only_filtered_neighbors_and_families() -> None:
    analysis = _analysis()
    rows = neighbour_rows(analysis, "T:a", families={"image"}, min_families=2)
    filtered = linked_subgraph(analysis, "T:a", rows, families={"image"})
    assert set(filtered.case_ids) == {"T:a", "T:b"}
    assert len(filtered.edges) == 1
    assert filtered.edges[0].signals == {"image": 0.9}
    assert filtered.edges[0].comparable == ["image"]
    assert [item.family for item in filtered.edges[0].evidence] == ["image"]
    assert set(analysis.edges[0].signals) == {"ids", "image", "text"}
