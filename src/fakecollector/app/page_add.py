"""Page "Dodaj reklamę": add one ad to the base and say where it belongs, and why."""

from __future__ import annotations

import hashlib
from pathlib import Path

import streamlit as st

from fakecollector.app import pl, state
from fakecollector.app.display import display_campaign_label, display_evidence
from fakecollector.app.links import FAMILY_ORDER
from fakecollector.core.schemas import Assignment
from fakecollector.graph.coverage import INSUFFICIENT_DATA
from fakecollector.ingest.normalize import display_text
from fakecollector.pipeline import assign_new
from fakecollector.store import RunStore

UPLOAD_TYPES = ["png", "jpg", "jpeg", "webp", "har", "html", "htm", "mhtml", "pdf", "mp4", "webm"]


def save_upload(run: Path, name: str, data: bytes) -> Path:
    """Store an upload under `<run>/uploads/<sha256>/<name>` (never executed, only parsed).

    The folder is the full content digest, so two different files can never share it and
    a committed case's input is never overwritten; the same bytes twice reuse the folder.
    """
    folder = run / "uploads" / hashlib.sha256(data).hexdigest()
    folder.mkdir(parents=True, exist_ok=True)
    safe = display_text(Path(name).name) or "upload"
    target = folder / safe
    target.write_bytes(data)
    return folder


def _show(answer: Assignment, run: Path) -> None:
    graph = state.analysis(run)
    labels = {c.id: display_campaign_label(c.label) for c in graph.campaigns}
    insufficient = answer.decision == "new" and INSUFFICIENT_DATA in answer.flags
    decision = (
        pl.ADD_INSUFFICIENT_DATA
        if insufficient
        else pl.ASSIGNMENT_DECISIONS.get(answer.decision, answer.decision)
    )
    show = (
        st.warning
        if insufficient
        else {"existing": st.success, "review": st.warning}.get(answer.decision, st.info)
    )
    show(f"**{decision}**")
    if insufficient:
        st.write(pl.ADD_INSUFFICIENT_EXPLANATION)
    if answer.duplicate_of:
        st.write(pl.ADD_DUPLICATE.format(case=answer.duplicate_of))
    cols = st.columns(3)
    campaign = labels.get(answer.campaign_id or "", answer.campaign_id or "—")
    cols[0].metric(pl.ADD_CAMPAIGN, campaign)
    cols[1].metric(pl.ADD_SCORE, f"{answer.score:.2f}")
    cols[2].metric(pl.ADD_MARGIN, f"{answer.margin:.2f}")
    if answer.operator_id:
        st.write(pl.ADD_OPERATOR.format(operator=answer.operator_id))
    if answer.toolkits:
        st.write(pl.ADD_TOOLKITS.format(toolkits=", ".join(answer.toolkits)))
    names = pl.FAMILY_NAMES
    missing = [f for f in FAMILY_ORDER if f not in answer.comparable]
    st.write(f"**{pl.ADD_COMPARABLE}:** " + (", ".join(names[f] for f in answer.comparable) or "—"))
    st.write(f"**{pl.ADD_MISSING}:** " + (", ".join(names[f] for f in missing) or "—"))
    st.subheader(pl.ADD_EVIDENCE)
    hints = [ev for ev in answer.evidence if ev.kind == "url.schema" and ev.weight == 0]
    evidence = [ev for ev in answer.evidence if not (ev.kind == "url.schema" and ev.weight == 0)]
    if not evidence:
        st.write(pl.ADD_NO_EVIDENCE)
    seen: set[tuple[str, str]] = set()
    for ev in sorted(evidence, key=lambda e: -e.weight):
        if (ev.family, ev.detail) in seen:
            continue  # the same trace seen in several matching cases
        seen.add((ev.family, ev.detail))
        st.write(f"- {names.get(ev.family, ev.family)}: {display_evidence(ev)} ({ev.weight:.2f})")
    if hints:
        st.subheader(pl.ADD_HINTS)
        for hint in hints:
            st.write(f"- {hint.detail}")
    st.caption(pl.ADD_SEE_LINKS.format(case=answer.case_id))


def render() -> None:
    """Form → `assign_new(commit=True)` → decision, comparable families, evidence."""
    st.header(pl.PAGE_ADD)
    run = state.run_dir()
    if not state.has_graph(run):
        st.info(pl.NO_RUN)
        return
    assert run is not None
    st.write(pl.ADD_INTRO)
    with st.form("add_ad", clear_on_submit=False):
        text = st.text_input(pl.ADD_URL)
        upload = st.file_uploader(pl.ADD_FILE, type=UPLOAD_TYPES)
        submitted = st.form_submit_button(pl.ADD_SUBMIT)
    if not submitted:
        return
    inputs: list[str | Path] = []
    if upload is not None:
        inputs.append(save_upload(run, upload.name, upload.getvalue()))
    elif text.strip():
        inputs.append(text.strip())
    if not inputs:
        st.warning(pl.ADD_EMPTY)
        return
    with st.spinner(pl.ADD_RUNNING):
        answers = assign_new(inputs, RunStore(run), commit=True)
    for answer in answers:
        _show(answer, run)


render()
