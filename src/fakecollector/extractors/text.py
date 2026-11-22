from __future__ import annotations

import logging
from collections.abc import Iterable
from functools import cache
from typing import TYPE_CHECKING, Literal

from fakecollector.core.extractor import BaseExtractor
from fakecollector.core.schemas import Artifact, Feature
from fakecollector.core.text import detect_lang, headline_template, minhash_vector, topic

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)
_SOURCES = frozenset({"text.raw", "html.title", "text.ocr", "text.asr"})


@cache
def _bge_model() -> SentenceTransformer | None:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        logger.warning("Skipping text.bge because sentence_transformers is unavailable")
        return None

    model = SentenceTransformer("BAAI/bge-m3")
    model.max_seq_length = 512
    if model.device.type == "cuda":
        model.half()
    return model


INPUT_LOCATOR = "input"
"""Locator of `text.raw` typed or pasted by the user (pipeline.assign_new)."""
_MAX_HEADLINE = 200


def _first_line(text: str) -> list[str]:
    """The first non-empty line of a plain text, when it is short enough to be a headline."""
    line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return [line] if line and len(line) <= _MAX_HEADLINE else []


def _derived(
    source: Feature,
    name: str,
    value: str = "",
    vector: list[float] | None = None,
    confidence: float = 1.0,
) -> Feature:
    return Feature(
        name=name,
        value=value,
        vector=vector,
        confidence=confidence,
        case_id=source.case_id,
        artifact_id=source.artifact_id,
        locator=f"from:{source.name}",
    )


class TextExtractor(BaseExtractor):
    """Derive case-level text signals from previously extracted content."""

    name = "text"
    version = 3
    stage = 2
    requires: Literal["base", "ml"] = "base"

    def __init__(self, known_names: Iterable[str] = (), *, enable_embeddings: bool = True) -> None:
        self._known_names = tuple(known_names)
        self._enable_embeddings = enable_embeddings

    def supports(self, artifact: Artifact) -> bool:
        """Accept any artifact because stage 2 uses prior case features."""
        return True

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        """Derive text signals from the case's prior features."""
        return self.extract_batch([artifact], [prior])[0]

    def extract_batch(
        self, artifacts: list[Artifact], priors: list[list[Feature]]
    ) -> list[list[Feature]]:
        """Batch embeddings across cases while keeping each case's output grouped."""
        results: list[list[Feature]] = []
        embedding_inputs: list[tuple[Feature, list[Feature]]] = []
        for _, prior in zip(artifacts, priors, strict=True):
            features: list[Feature] = []
            results.append(features)
            sources = sorted(
                (source for source in prior if source.name in _SOURCES),
                key=lambda source: (
                    source.case_id,
                    source.artifact_id,
                    source.name,
                    source.locator,
                    source.value,
                ),
            )
            # OCR's title-like blocks (B2d); the first OCR line is usually UI chrome.
            ocr_headlines: dict[tuple[str, str], list[str]] = {}
            for f in prior:
                if f.name == "ocr.headline":
                    ocr_headlines.setdefault((f.artifact_id, f.locator), []).append(f.value)
            for source in sources:
                sketch = minhash_vector(source.value)
                if sketch is None:
                    continue
                features.append(_derived(source, "text.minhash", vector=sketch))
                headlines: list[str] = []
                if source.name == "html.title":
                    headlines = [source.value]
                elif source.name == "text.ocr":
                    # A screenshot's own title block counts even next to a page title: the ad
                    # creative of a case carries the story line the landing page may not.
                    # Without a title block there is no headline: the normalised OCR text
                    # is one line of UI chrome and body text, not a title.
                    headlines = ocr_headlines.get((source.artifact_id, source.locator), [])
                elif source.name == "text.raw" and source.locator == INPUT_LOCATOR:
                    # Pasted text or a .txt description: its first line is the headline.
                    headlines = _first_line(source.value)
                for headline in headlines:
                    if template := headline_template(headline, self._known_names):
                        features.append(_derived(source, "text.headline_tpl", value=template))
                features.append(_derived(source, "text.lang", value=detect_lang(source.value)))
                if subject := topic(source.value):
                    name, score = subject
                    features.append(_derived(source, "text.topic", value=name, confidence=score))
                embedding_inputs.append((source, features))

        if self._enable_embeddings and embedding_inputs and (model := _bge_model()) is not None:
            vectors = model.encode(
                [source.value for source, _ in embedding_inputs],
                batch_size=64,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            for (source, features), vector in zip(embedding_inputs, vectors, strict=True):
                features.append(_derived(source, "text.bge", vector=vector.tolist()))
        return results
