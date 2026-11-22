from fakecollector.api.views import case_title, defang, human_label, plural, short


def test_human_label_masks_and_capitalises() -> None:
    assert human_label("pilne : atak na {PERSON} po {NUM} dniach_") == (
        "Pilne: atak na [osoba] po N dniach"
    )
    assert human_label("atak na {PERSON}", person="Jan Kowalski") == "Atak na Jan Kowalski"


def test_defang_and_short() -> None:
    assert defang("example.com/path.html") == "example[.]com/path.html"
    assert len(short("x" * 200)) <= 56
    assert short("abc") == "abc"


def test_polish_plural() -> None:
    forms = ("plik", "pliki", "plików")
    assert plural(1, forms) == "1 plik"
    assert plural(3, forms) == "3 pliki"
    assert plural(12, forms) == "12 plików"
    assert plural(22, forms) == "22 pliki"


def test_case_title_uses_corpus_name() -> None:
    assert case_title("upload:abc") == "Przesłane · abc"


def test_error_page_text_is_recognised() -> None:
    from fakecollector.api.views import _ERROR_PAGE

    assert _ERROR_PAGE.search("bad gateway error code 502 visit cloudflare com")
    assert _ERROR_PAGE.search("example.click | 502: Bad gateway")
    assert not _ERROR_PAGE.search("sponsorowane dowiedz się więcej wtorek 20.10 warszawa")


def test_human_label_capitalises_sentences() -> None:
    from fakecollector.api.views import human_label

    assert human_label("{NUM} minut po emisji. nagranie usunięto") == (
        "N minut po emisji. Nagranie usunięto"
    )


def test_polish_plural_forms_for_reports_pairs_and_files() -> None:
    from fakecollector.api import pl
    from fakecollector.api.views import plural, plural_word

    expected = {1: "zgłoszenie", 2: "zgłoszenia", 4: "zgłoszenia", 5: "zgłoszeń", 12: "zgłoszeń"}
    expected |= {14: "zgłoszeń", 21: "zgłoszeń", 22: "zgłoszenia", 25: "zgłoszeń"}
    expected |= {100: "zgłoszeń", 102: "zgłoszenia", 112: "zgłoszeń", 0: "zgłoszeń"}
    for count, word in expected.items():
        assert plural_word(count, pl.REPORTS) == word, count
    assert plural(1, pl.POSSIBLE_PAIRS) == "1 możliwej pary"
    assert plural(15, pl.POSSIBLE_PAIRS) == "15 możliwych par"
    assert plural(1, pl.IDENTICAL_FILES_INSTR) == "1 identycznym plikiem"
    assert plural(21, pl.IDENTICAL_FILES_INSTR) == "21 identycznymi plikami"
    assert plural(3, pl.IDENTICAL_FILES) == "3 identyczne pliki"
    assert plural(1, pl.REPORTS_LOCATIVE) == "1 zgłoszeniu"


def test_join_and_similarity_helpers() -> None:
    from fakecollector.api.views import _join, _similarity

    assert _join([]) == ""
    assert _join(["a"]) == "a"
    assert _join(["a", "b", "c"]) == "a, b i c"
    assert _similarity("J 0.91") == 0.91
    assert _similarity("cos 1.00") == 1.0
    assert _similarity("H 0/256") is None


def test_face_reference_lookup_rejects_unsafe_slugs() -> None:
    from fakecollector.api.views import face_ref_file

    assert face_ref_file("../../etc/passwd") is None
    assert face_ref_file("Jan Kowalski") is None
    assert face_ref_file("nobody-with-this-slug") is None


def test_prose_sentences_are_told_from_menus() -> None:
    from fakecollector.api.views import _norm, _prose

    assert _prose("Wszystko zaczęło się od anonimowego listu, który trafił wczoraj do redakcji.")
    assert not _prose("WIADOMOŚCI EKONOMIA REGIONY ŚWIAT TECHNOLOGIE SPORT MODA WIDEO BLOG.")
    assert not _prose("Za krótkie zdanie.")
    assert _norm("  Ten  SAM\ttekst ") == "ten sam tekst"


def test_labels_never_show_raw_internal_ids() -> None:
    import re

    from fakecollector.api import pl
    from fakecollector.core.registry import FEATURES
    from fakecollector.graph.assign import NEAREST_KIND

    raw_id = re.compile(r"[a-z]+\.[a-z_]+")
    kinds = [*FEATURES, NEAREST_KIND, "made.up_kind"]
    labels = [pl.kind_label(kind) for kind in kinds]
    labels += [pl.type_label(t) for t in [*pl.ENTITY_TYPES, "MadeUpType"]]
    labels += [pl.family_label(f) for f in [*pl.FAMILY_NAMES, "made.up"]]
    labels += [pl.flag_label(f) for f in [*pl.FLAGS, "made.up_flag"]]
    labels += [*pl.REPORT_TIERS.values(), *pl.DECISIONS.values(), *pl.ROLES.values()]
    for label in labels:
        assert label and not raw_id.fullmatch(label), label
        assert not re.search(r"\b[a-z]+\.[a-z_]+\b", label) or "[.]" in label or "." not in label, (
            label
        )
    assert pl.kind_label(NEAREST_KIND) == pl.UNKNOWN_KIND


def test_upload_ids_and_repeat_detection() -> None:
    from fakecollector.api.uploads import UPLOAD_ID, existing_upload

    assert UPLOAD_ID.fullmatch("U:03e3e372")
    assert UPLOAD_ID.fullmatch("U:03e3e372-2")
    assert not UPLOAD_ID.fullmatch("nask_backup:p1")
    assert not UPLOAD_ID.fullmatch("U:../../etc")
    known = {"U:03e3e372", "nask_backup:p1"}
    assert existing_upload("U:03e3e372-2", known) == "U:03e3e372"
    assert existing_upload("U:03e3e372", known) is None
    assert existing_upload("U:aaaaaaaa-2", known) is None


def test_remove_upload_refuses_corpus_cases(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from fakecollector.api.uploads import remove_upload, write_lock
    from fakecollector.store import RunStore

    with write_lock(tmp_path):
        assert remove_upload(RunStore(tmp_path), "nask_backup:p1") is False
