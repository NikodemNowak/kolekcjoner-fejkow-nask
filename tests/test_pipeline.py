import io
import os
from email.message import EmailMessage
from pathlib import Path
from typing import Literal

import pytest
from PIL import Image

from fakecollector.core.extractor import BaseExtractor
from fakecollector.core.schemas import Artifact, Case, Feature
from fakecollector.pipeline import analyze, assign_new, extract, ingest
from fakecollector.store import FeatureCache, RunStore


class CountingExtractor(BaseExtractor):
    name = "counting"
    version = 1
    cacheable = True

    def __init__(self) -> None:
        self.calls = 0

    def supports(self, artifact: Artifact) -> bool:
        return True

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        self.calls += 1
        return [Feature(case_id=artifact.case_id, artifact_id=artifact.id, name="test", value="v")]


class BrokenExtractor(CountingExtractor):
    name = "broken"
    cacheable = False

    def extract(self, artifact: Artifact, prior: list[Feature]) -> list[Feature]:
        raise ValueError("broken")


class SecondExtractor(CountingExtractor):
    name = "second"


class ModelExtractor(CountingExtractor):
    name = "model"
    requires: Literal["base", "ml"] = "ml"


def test_extract_reuses_cache_and_skips_failures_and_ml(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("synthetic", encoding="utf-8")
    store = RunStore(tmp_path / "run")
    store.write_cases(
        [Case(id="c", corpus="fixture", path=path)],
        [Artifact(id="a", case_id="c", kind="text", role="other", path=path, size=9)],
    )
    cache = FeatureCache(tmp_path / "cache")
    counting, second, model = CountingExtractor(), SecondExtractor(), ModelExtractor()
    extract(store, "fast", cache=cache, extractors=[BrokenExtractor(), counting, second, model])
    extract(store, "fast", cache=cache, extractors=[BrokenExtractor(), counting, second, model])
    assert counting.calls == 1
    assert second.calls == 1
    assert model.calls == 0
    assert [feature.value for feature in store.features()] == ["v", "v"]


def test_assign_url_is_passive_and_commit_preserves_existing_campaign(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run")
    path = tmp_path / "base.txt"
    path.write_text("base", encoding="utf-8")
    store.write_cases(
        [Case(id="base", corpus="fixture", path=path)],
        [Artifact(id="base", case_id="base", kind="text", role="other", path=path, size=4)],
    )
    original = analyze(store)
    result = assign_new(["https://unrelated.example.invalid/a?campaign_id=4"], store)
    assert result[0].decision == "new"
    assert store.load_graph() == original
    committed = assign_new(
        ["https://unrelated.example.invalid/a?campaign_id=4"], store, commit=True
    )
    assert committed[0].decision == "new"
    assert original.campaigns[0].id in {campaign.id for campaign in store.load_graph().campaigns}
    assert len(store.cases()) == 2


def test_assign_text_hint_is_accepted(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run")
    store.write_cases([Case(id="base", corpus="fixture", path=None)], [])
    analyze(store)
    result = assign_new(["Synthetic product name"], store)
    assert len(result) == 1
    assert result[0].decision == "new"


def test_assign_commit_persists_duplicate_reference(tmp_path: Path) -> None:
    page = tmp_path / "page.html"
    page.write_text("<html><title>Synthetic example</title><p>Example text.</p></html>")
    store = RunStore(tmp_path / "run")
    ingest([page], store)
    extract(store)
    analyze(store)
    [result] = assign_new([page], store, commit=True)
    assert result.duplicate_of is not None
    committed = next(case for case in store.cases() if case.id == result.case_id)
    assert committed.duplicate_of == result.duplicate_of


def test_reextract_after_commit_does_not_duplicate_features(tmp_path: Path) -> None:
    page = tmp_path / "page.html"
    page.write_text("<html><title>Synthetic example</title><p>Example text.</p></html>")
    store = RunStore(tmp_path / "run")
    ingest([page], store)
    extract(store)
    analyze(store)
    [result] = assign_new([page], store, commit=True)
    before = [feature for feature in store.all_features() if feature.case_id == result.case_id]
    assert before
    extract(store)
    after = [feature for feature in store.all_features() if feature.case_id == result.case_id]
    assert sorted(feature.model_dump_json() for feature in after) == sorted(
        feature.model_dump_json() for feature in before
    )


def test_reextract_keeps_committed_url_only_features(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run")
    store.write_cases([Case(id="base", corpus="fixture", path=None)], [])
    analyze(store)
    [result] = assign_new(["https://synthetic.example/path?campaign_id=123"], store, commit=True)
    before = {
        (feature.name, feature.value)
        for feature in store.all_features()
        if feature.case_id == result.case_id
    }
    assert ("url.domain", "synthetic.example") in before
    extract(store)
    after = {
        (feature.name, feature.value)
        for feature in store.all_features()
        if feature.case_id == result.case_id
    }
    assert before <= after


def test_ingest_invalidates_previous_results(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run")
    old = Case(id="old", corpus="fixture", path=None)
    store.write_cases([old], [])
    store.add_features(
        [Feature(case_id="old", artifact_id="x", name="text.raw", value="old")], "test", 1
    )
    analyze(store)
    new_input = tmp_path / "new.txt"
    new_input.write_text("new", encoding="utf-8")
    ingest([new_input], store)
    assert store.features() == []
    assert not (store.run_dir / "graph.json").exists()


def test_fast_profile_does_not_load_text_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def model() -> None:
        calls.append(True)
        return None

    monkeypatch.setattr("fakecollector.extractors.text._bge_model", model)
    page = tmp_path / "page.html"
    page.write_text("<html><body>One two three four five six seven eight.</body></html>")
    store = RunStore(tmp_path / "run")
    ingest([page], store)
    extract(store, "fast")
    assert not calls
    assert any(feature.name == "text.minhash" for feature in store.features())


def test_ingest_handles_non_utf8_corpus_path(tmp_path: Path) -> None:
    root = tmp_path / os.fsdecode(b"corpus-\xff")
    case = root / "one"
    case.mkdir(parents=True)
    (case / "page.html").write_text("<p>synthetic</p>", encoding="utf-8")
    store = RunStore(tmp_path / "run")
    ingest([root], store)
    assert len(store.cases()) == 1
    assert store.artifacts()[0].path.read_text() == "<p>synthetic</p>"


def test_extract_derives_images_from_mhtml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKECOLLECTOR_B_CACHE", str(tmp_path / "derived"))
    image = Image.effect_noise((160, 160), 40).convert("RGB")
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    message = EmailMessage()
    message.set_content("Synthetic archived page")
    message.add_attachment(encoded.getvalue(), maintype="image", subtype="png")
    archive = tmp_path / "page.mhtml"
    archive.write_bytes(message.as_bytes())
    store = RunStore(tmp_path / "run")
    ingest([archive], store)
    extract(store, "fast")
    derived = [a for a in store.artifacts() if a.parent_id is not None]
    assert derived
    assert any(f.name == "img.phash" and f.artifact_id == derived[0].id for f in store.features())


def test_assign_bare_domain_on_unseen_domain_says_insufficient_data(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run")
    path = tmp_path / "base.txt"
    path.write_text("base", encoding="utf-8")
    store.write_cases(
        [Case(id="base", corpus="fixture", path=path)],
        [Artifact(id="base", case_id="base", kind="text", role="other", path=path, size=4)],
    )
    analyze(store)
    for value in ("unrelated.example.invalid", "https://unrelated.example.invalid/a?x=1"):
        (result,) = assign_new([value], store)
        assert result.decision == "new"
        assert result.flags == ["insufficient_data"]
    assert assign_new([str(tmp_path / "missing.png")], store) == []


def _mhtml_archive(path: Path) -> Path:
    from email.mime.image import MIMEImage
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    image = Image.effect_noise((160, 160), 40).convert("RGB")
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    msg = MIMEMultipart("related", type="text/html")
    msg["Snapshot-Content-Location"] = "https://synthetic-offer.example/landing"
    page = MIMEText(
        "<html><head><title>Synthetic offer page</title></head>"
        "<body><p>Visible synthetic text</p>"
        "<script src='https://cdn.synthetic-kit.example/k.js'></script></body></html>",
        "html",
    )
    page["Content-Location"] = "https://synthetic-offer.example/landing"
    msg.attach(page)
    msg.attach(MIMEImage(encoded.getvalue(), "png"))
    path.write_bytes(msg.as_bytes())
    return path


def test_extract_runs_html_extractors_on_mhtml_only_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKECOLLECTOR_B_CACHE", str(tmp_path / "derived"))
    case = tmp_path / "corpus" / "case1"
    case.mkdir(parents=True)
    _mhtml_archive(case / "page.mhtml")
    store = RunStore(tmp_path / "run")
    ingest([tmp_path / "corpus"], store)
    extract(store, "fast")
    names = {f.name for f in store.features()}
    assert {"html.title", "text.raw", "url.domain", "img.phash"} <= names
    pages = [a for a in store.artifacts() if a.kind == "html"]
    assert len(pages) == 1 and pages[0].meta["locator"].startswith("mhtml:part=")
    title = next(f for f in store.features() if f.name == "html.title")
    assert title.artifact_id == pages[0].id


def test_mhtml_page_is_skipped_when_capture_has_saved_html(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKECOLLECTOR_B_CACHE", str(tmp_path / "derived"))
    case = tmp_path / "corpus" / "case1"
    case.mkdir(parents=True)
    _mhtml_archive(case / "page.mhtml")
    (case / "page.html").write_text("<html><title>Saved</title></html>", encoding="utf-8")
    store = RunStore(tmp_path / "run")
    ingest([tmp_path / "corpus"], store)
    extract(store, "fast")
    assert [a.path.name for a in store.artifacts() if a.kind == "html"] == ["page.html"]


def _har_case(folder: Path) -> Path:
    import base64
    import json

    image = Image.effect_noise((160, 160), 40).convert("RGB")
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    page = (
        b"<html><head><title>Synthetic offer page</title></head>"
        b"<body><p>Visible synthetic text about a synthetic offer</p></body></html>"
    )

    def entry(url: str, mime: str, body: bytes, kind: str) -> dict[str, object]:
        return {
            "_resourceType": kind,
            "request": {"method": "GET", "url": url},
            "response": {
                "status": 200,
                "headers": [],
                "content": {
                    "mimeType": mime,
                    "text": base64.b64encode(body).decode(),
                    "encoding": "base64",
                },
            },
        }

    har = {
        "log": {
            "creator": {"name": "synthetic"},
            "pages": [{"title": "https://synthetic-offer.example/landing"}],
            "entries": [
                entry("https://synthetic-offer.example/landing", "text/html", page, "document"),
                entry(
                    "https://synthetic-offer.example/hero.png",
                    "image/png",
                    encoded.getvalue(),
                    "image",
                ),
            ],
        }
    }
    folder.mkdir(parents=True)
    path = folder / "capture.har"
    path.write_text(json.dumps(har), encoding="utf-8")
    return path


def test_extract_reads_page_and_images_kept_in_a_har(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Audit 03: HAR-only inputs carried the landing HTML and images but gave no text,
    # template or image features.
    monkeypatch.setenv("FAKECOLLECTOR_B_CACHE", str(tmp_path / "derived"))
    _har_case(tmp_path / "corpus" / "case1")
    store = RunStore(tmp_path / "run")
    ingest([tmp_path / "corpus"], store)
    extract(store, "fast")
    names = {f.name for f in store.features()}
    assert {"html.title", "text.raw", "img.phash"} <= names
    derived = {a.kind: a for a in store.artifacts() if a.parent_id is not None}
    assert derived["html"].meta["locator"] == "har:entry[0]"
    assert derived["html"].meta["url"] == "https://synthetic-offer.example/landing"
    assert derived["image"].meta["locator"] == "har:entry[1]"


def test_har_body_is_not_added_when_the_capture_has_its_saved_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKECOLLECTOR_B_CACHE", str(tmp_path / "derived"))
    case = tmp_path / "corpus" / "case1"
    _har_case(case)
    (case / "page.html").write_text("<html><title>Saved</title></html>", encoding="utf-8")
    (case / "page_files").mkdir()
    Image.effect_noise((150, 150), 30).convert("RGB").save(case / "page_files" / "a.png")
    store = RunStore(tmp_path / "run")
    ingest([tmp_path / "corpus"], store)
    extract(store, "fast")
    assert not [a for a in store.artifacts() if a.parent_id is not None and a.kind != "asset"]


def test_assign_bare_domain_is_a_url_input(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run")
    store.write_cases([Case(id="base", corpus="fixture", path=None)], [])
    analyze(store)
    for raw in ["evil-site.live", "evil-site.live/oferta"]:
        result = assign_new([raw], store)
        assert len(result) == 1, raw  # used to log "Input does not exist" and return []


def _empty_run(tmp_path: Path) -> RunStore:
    store = RunStore(tmp_path / "run")
    store.write_cases([Case(id="base", corpus="fixture", path=None)], [])
    analyze(store)
    return store


def test_assign_pasted_sentence_is_text_input(tmp_path: Path) -> None:
    store = _empty_run(tmp_path)
    features: list[Feature] = []
    text = "Szokujące wyznanie. Zarabia 30 000 zł miesięcznie dzięki nowej platformie/aplikacji"
    (result,) = assign_new([text], store, commit=False, features_out=features)
    assert result.decision == "new"
    raw = [f for f in features if f.name == "text.raw"]
    assert [f.value for f in raw] == [text]
    assert any(f.name == "text.headline_tpl" for f in features)


@pytest.mark.parametrize("layout", ["loose", "folder"])
def test_assign_plain_text_file_yields_text_features(tmp_path: Path, layout: str) -> None:
    store = _empty_run(tmp_path)
    text = "Smutna wiadomość dla całej Polski\nZnany prezenter stracił wszystko w jeden dzień"
    if layout == "loose":
        source = tmp_path / "nagłówek.txt"
    else:
        (tmp_path / "upload").mkdir()
        source = tmp_path / "upload" / "opis.txt"
    source.write_text(text, encoding="utf-8")
    features: list[Feature] = []
    target = source if layout == "loose" else source.parent
    (result,) = assign_new([str(target)], store, commit=False, features_out=features)
    assert result.decision == "new"
    assert "insufficient_data" not in result.flags
    assert [f.value for f in features if f.name == "text.raw"] == [text]
    templates = [f.value for f in features if f.name == "text.headline_tpl"]
    assert templates == ["smutna wiadomość dla całej polski"]


def test_assign_empty_text_folder_is_flagged(tmp_path: Path) -> None:
    store = _empty_run(tmp_path)
    (tmp_path / "upload").mkdir()
    (tmp_path / "upload" / "opis.txt").write_text("  ", encoding="utf-8")
    (result,) = assign_new([str(tmp_path / "upload")], store, commit=False)
    assert result.decision == "new"
    assert result.flags == ["insufficient_data"]
