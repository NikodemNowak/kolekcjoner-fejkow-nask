"""Extractor protocol and base class (Task 0)."""

from __future__ import annotations

from typing import Literal, Protocol

from fakecollector.core.schemas import Artifact, Feature


class Extractor(Protocol):
    """A feature extractor: one artifact in, a list of features out."""

    name: str
    version: int
    stage: int
    requires: Literal["base", "ml"]

    def supports(self, artifact: Artifact) -> bool:
        """Return True if this extractor can read the artifact."""
        ...

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        """Extract features from one artifact."""
        ...

    def extract_batch(
        self, artifacts: list[Artifact], priors: list[list[Feature]]
    ) -> list[list[Feature]]:
        """Extract features from many artifacts (GPU extractors override this)."""
        ...


class BaseExtractor:
    """Default implementation: `extract_batch` loops over `extract`."""

    name: str = "base"
    version: int = 1
    stage: int = 1
    requires: Literal["base", "ml"] = "base"

    def supports(self, artifact: Artifact) -> bool:
        """Return True if this extractor can read the artifact."""
        raise NotImplementedError

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        """Extract features from one artifact."""
        raise NotImplementedError

    def extract_batch(
        self, artifacts: list[Artifact], priors: list[list[Feature]]
    ) -> list[list[Feature]]:
        """Loop over `extract`; override for batched GPU inference."""
        return [self.extract(a, p) for a, p in zip(artifacts, priors, strict=True)]
