from pathlib import Path

from fakecollector.core.extractor import BaseExtractor, Extractor
from fakecollector.core.schemas import Artifact, Feature


class _Echo(BaseExtractor):
    name = "echo"

    def supports(self, artifact: Artifact) -> bool:
        return True

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        return [
            Feature(case_id=artifact.case_id, artifact_id=artifact.id, name="text.raw", value="x")
        ]


def test_base_extract_batch_loops_over_extract() -> None:
    arts = [
        Artifact(id=f"{i:016x}", case_id="T:1", kind="text", role="other", path=Path("a"), size=1)
        for i in range(3)
    ]
    ex: Extractor = _Echo()
    out = ex.extract_batch(arts, [[], [], []])
    assert [fs[0].artifact_id for fs in out] == [a.id for a in arts]
