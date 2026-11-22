from fakecollector.api.assign import _CFG, Verdict
from fakecollector.graph.config import EdgeConfig


def test_verdict_exposes_the_assignment_thresholds() -> None:
    assert {"threshold", "min_margin", "strong_link"} <= set(Verdict.model_fields)
    defaults = EdgeConfig()
    assert _CFG.tau_assign == defaults.tau_assign
    assert _CFG.assign_margin == defaults.assign_margin
    assert _CFG.strong_link == defaults.strong_link
