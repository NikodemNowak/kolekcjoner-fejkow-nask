"""Prepare requested downloads without changing the source analysis."""

from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

from pydantic import BaseModel

from fakecollector.export import FORMATS, export_all
from fakecollector.report.build import build_report
from fakecollector.store import RunStore


class PreparedExport(BaseModel):
    """A named download and its MIME type."""

    filename: str
    mime: str
    content: bytes


def prepare_export(store: RunStore, format_name: str) -> PreparedExport:
    """Generate a report or one export format from the current persisted analysis."""
    if format_name not in {"report", "json", *FORMATS}:
        raise ValueError(f"Unsupported export format: {format_name}")
    analysis = store.load_graph()
    if format_name == "json":
        return PreparedExport(
            filename="graph.json",
            mime="application/json",
            content=analysis.model_dump_json(indent=2).encode("utf-8"),
        )
    with tempfile.TemporaryDirectory(prefix="fakecollector-export-") as temporary:
        root = Path(temporary)
        if format_name == "report":
            copy = RunStore(root / "run")
            copy.write_cases(store.cases(), store.artifacts())
            copy.save_graph(analysis)
            return PreparedExport(
                filename="report.html", mime="text/html", content=build_report(copy).read_bytes()
            )
        paths = export_all(
            analysis, store.all_features(), root, [format_name], store.cases(), store.artifacts()
        )[format_name]
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(paths):
                archive.write(path, arcname=path.relative_to(root).as_posix())
        return PreparedExport(
            filename=f"{format_name}.zip", mime="application/zip", content=buffer.getvalue()
        )
