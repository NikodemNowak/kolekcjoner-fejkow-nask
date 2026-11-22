"""Load gold labels with the strict or lenient campaign convention."""

from __future__ import annotations

from csv import DictReader
from pathlib import Path

from pydantic import BaseModel, Field


class GoldLabel(BaseModel):
    """Expected campaign, operator and toolkit memberships for one case."""

    case_id: str
    campaign: str
    operator: str | None = None
    toolkit: list[str] = Field(default_factory=list)
    note: str = ""


def load_gold(path: Path, *, strict: bool = True) -> dict[str, GoldLabel]:
    """Read a gold CSV, splitting disputed campaign D into singletons in lenient mode."""
    labels: dict[str, GoldLabel] = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = DictReader(stream)
        columns = {"case_id", "campaign", "operator", "toolkit", "note"}
        if rows.fieldnames is None or set(rows.fieldnames) != columns:
            raise ValueError(f"{path}: expected columns {', '.join(sorted(columns))}")
        for row in rows:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{path}:{rows.line_num}: wrong number of columns")
            case_id = row["case_id"].strip()
            if not case_id or case_id in labels:
                raise ValueError(f"{path}:{rows.line_num}: empty or repeated case ID {case_id!r}")
            campaign = row["campaign"].strip()
            if not campaign or (campaign == "D" and not strict):
                campaign = f"S:{case_id}"
            labels[case_id] = GoldLabel(
                case_id=case_id,
                campaign=campaign,
                operator=row["operator"].strip() or None,
                toolkit=[name for part in row["toolkit"].split(";") if (name := part.strip())],
                note=row["note"].strip(),
            )
    return labels
