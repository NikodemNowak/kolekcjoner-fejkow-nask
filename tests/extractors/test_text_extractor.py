from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import numpy as np
import numpy.typing as npt
import pytest

from fakecollector.core.schemas import Artifact, Feature
from fakecollector.extractors import text
from fakecollector.extractors.text import TextExtractor


@pytest.fixture(autouse=True)
def _optional_model(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    text._bge_model.cache_clear()
    if request.node.get_closest_marker("gpu") is None:
        monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    yield
    text._bge_model.cache_clear()


def _artifact(case_id: str = "synthetic-case") -> Artifact:
    return Artifact(
        id="unused", case_id=case_id, kind="text", role="other", path=Path("unused"), size=0
    )


def _source(value: str, name: str = "text.raw", artifact_id: str = "source") -> Feature:
    return Feature(case_id="synthetic-case", artifact_id=artifact_id, name=name, value=value)


def test_text_extracts_matching_headline_templates() -> None:
    extractor = TextExtractor()
    titles = [
        "PILNE: Szokujące nagranie z Janem Kowalskim tuż po programie",
        "PILNE: Szokujące nagranie z Anną Nowak tuż po programie",
        "Nowa wystawa fotografii przyrodniczej już w sobotę",
    ]
    templates = [
        next(
            feature.value
            for feature in extractor.extract(_artifact(), [_source(title, "html.title")])
            if feature.name == "text.headline_tpl"
        )
        for title in titles
    ]
    assert templates[0] == templates[1] == "pilne: szokujące nagranie z {PERSON} tuż po programie"
    assert templates[0] != templates[2]


@pytest.mark.parametrize("value", ["", "Zysk bez ryzyka", " !!! "])
def test_text_skips_empty_and_short_sources(value: str) -> None:
    assert TextExtractor().extract(_artifact(), [_source(value, "html.title")]) == []


def test_text_preserves_provenance_and_stable_order() -> None:
    extractor = TextExtractor()
    artifact = _artifact()
    prior = [
        _source("Wpłać depozyt i inwestuj w akcje dla zysku.", artifact_id="html-source"),
        _source("This is an offer that can help you.", "text.asr", "audio-source"),
        _source("Loteria fantowa rusza w sobotę.", "text.unrelated", "ignored"),
    ]
    assert extractor.supports(artifact)
    actual = extractor.extract(artifact, prior)
    assert actual == extractor.extract(artifact, prior[::-1])
    assert {feature.name for feature in actual} == {"text.minhash", "text.lang", "text.topic"}
    assert {"pl", "en"} == {feature.value for feature in actual if feature.name == "text.lang"}
    sources = {feature.artifact_id: feature for feature in prior[:2]}
    for feature in actual:
        source = sources[feature.artifact_id]
        assert feature.case_id == source.case_id
        assert feature.locator == f"from:{source.name}"
    subject = next(feature for feature in actual if feature.name == "text.topic")
    assert subject.value == "investment"
    assert subject.confidence == pytest.approx(5 / 8)


def test_text_ocr_without_title_block_gives_no_headline() -> None:
    """Normalised OCR text is one line of chrome and body text, never a headline itself."""
    extractor = TextExtractor()
    ocr = _source("Nocna loteria przydziela losy\nNowa szansa na wysoką nagrodę", "text.ocr")
    title = _source("Zabytkowy zegar wrócił do muzeum", "html.title")
    for prior, expected in [
        ([ocr], []),
        ([ocr, title], [title.value.lower()]),
    ]:
        templates = [
            feature.value
            for feature in extractor.extract(_artifact(), prior)
            if feature.name == "text.headline_tpl"
        ]
        assert templates == expected


def test_text_warns_once_when_embeddings_are_unavailable(caplog: pytest.LogCaptureFixture) -> None:
    prior = [_source("Oferta jest dziś dostępna dla każdego.")]
    TextExtractor().extract(_artifact(), prior)
    TextExtractor().extract(_artifact(), prior)
    assert sum("sentence_transformers" in record.message for record in caplog.records) == 1


def test_text_batches_embeddings_and_keeps_case_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    class StubModel:
        def __init__(self, model_name: str) -> None:
            assert model_name == "BAAI/bge-m3"
            self.max_seq_length = 0

        @property
        def device(self) -> type:
            return type("Device", (), {"type": "cpu"})

        def encode(
            self,
            values: list[str],
            *,
            batch_size: int,
            normalize_embeddings: bool,
            convert_to_numpy: bool,
            show_progress_bar: bool,
        ) -> npt.NDArray[np.float32]:
            assert self.max_seq_length == 512
            assert batch_size == 64 and normalize_embeddings and convert_to_numpy
            assert not show_progress_bar
            calls.append(values)
            return np.eye(len(values), 1024, dtype=np.float32)

    module = ModuleType("sentence_transformers")
    module.SentenceTransformer = StubModel
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    first = _source("Oferta jest dziś dostępna dla każdego.", artifact_id="first")
    second = _source("Przygotuj się na wielką wygraną.", artifact_id="second").model_copy(
        update={"case_id": "case-2"}
    )
    results = TextExtractor().extract_batch(
        [_artifact(), _artifact(), _artifact("case-2")], [[first], [], [second]]
    )
    assert calls == [[first.value, second.value]]
    assert results[1] == []
    for index, source, result in [(0, first, results[0]), (1, second, results[2])]:
        embedding = next(feature for feature in result if feature.name == "text.bge")
        assert embedding.vector is not None
        assert embedding.vector[index] == 1.0
        assert (embedding.case_id, embedding.artifact_id) == (source.case_id, source.artifact_id)


@pytest.mark.gpu
def test_bge_prefers_paraphrases() -> None:
    pytest.importorskip("sentence_transformers", exc_type=ImportError)
    texts = [
        "Wpłać pieniądze na naszą platformę inwestycyjną i szybko pomnóż swoje oszczędności.",
        "Nasz serwis pozwala łatwo zwiększyć kapitał po dokonaniu wpłaty na inwestycje.",
        "Wiosną żurawie wracają na mokradła i zakładają gniazda wśród trzcin.",
    ]
    output = TextExtractor().extract_batch([_artifact()] * 3, [[_source(value)] for value in texts])
    vectors = [
        np.asarray(next(feature.vector for feature in group if feature.name == "text.bge"))
        for group in output
    ]
    assert all(vector.shape == (1024,) for vector in vectors)
    assert np.linalg.norm(vectors, axis=1) == pytest.approx([1.0] * 3, abs=1e-3)
    anchor, related, unrelated = vectors
    assert np.dot(anchor, related) > np.dot(anchor, unrelated) + 0.1


def test_text_headline_prefers_ocr_headline_over_first_line() -> None:
    """B2d: the OCR title line, not the first OCR line (UI chrome), feeds headline_tpl."""
    ocr = _source("12:41 87% strona testowa sponsorowane nowy program dla każdego", "text.ocr")
    headline = _source("Nowy program oszczędnościowy dla każdego", "ocr.headline")
    other = _source("Inny tytuł z innego zrzutu ekranu", "ocr.headline", artifact_id="other")
    templates = [
        feature.value
        for feature in TextExtractor().extract(_artifact(), [ocr, headline, other])
        if feature.name == "text.headline_tpl"
    ]
    assert templates == ["nowy program oszczędnościowy dla każdego"]


def test_text_templates_every_ocr_headline_even_with_page_title() -> None:
    """A case's ad screenshot keeps its story line next to the landing page title."""
    title = _source("Strona główna portalu z wiadomościami dnia", "html.title")
    ocr = _source("sponsorowane duży napis wydarzenie które zmieniło kraj", "text.ocr")
    big = _source("Duży napis na grafice", "ocr.headline")
    card = _source("Wydarzenie, które zmieniło kraj", "ocr.headline")
    templates = {
        feature.value
        for feature in TextExtractor().extract(_artifact(), [title, ocr, big, card])
        if feature.name == "text.headline_tpl"
    }
    assert templates == {
        "strona główna portalu z wiadomościami dnia",
        "duży napis na grafice",
        "wydarzenie które zmieniło kraj",
    }
