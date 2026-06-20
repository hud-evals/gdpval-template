"""Grader — medsec-pathology-forms. Plain, readable. Tuned to the REAL GDPval file.

Real reference file `July 2025 - Bulk Form Needed.xlsx`: a title row, then a
header row (Lab Name | Patient ID | Patient First Name | Patient Last Name |
Date Of Birth | Pathology Accession # | Request Sent Date) and 30 patient rows
across three labs (Minnesota / Arizona / Canyon Pathology). The task splits the
form into one sheet per lab.

Deterministic axis (0.55): recover each patient's correct lab from the form, then
check the agent's per-lab sheets — one sheet per lab, every patient on the right
lab's sheet (F1 by Patient ID), and the required patient columns present.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[2]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import deliverable_io as dio
import native_grading

DET_WEIGHT = 0.55
AXIS_WEIGHTS = {
    "factual_accuracy": 0.28,
    "professional_judgment": 0.18,
    "evidence_grounding": 0.18,
    "completeness": 0.18,
    "format_regulatory_compliance": 0.10,
    "clarity": 0.08,
}


def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _find_header(rows: list[list[Any]]) -> tuple[int, list[str]] | None:
    for i, r in enumerate(rows):
        cells = [str(c).strip() if c is not None else "" for c in r]
        if any(c == "Lab Name" for c in cells) and any("Patient ID" in c for c in cells):
            return i, cells
    return None


def _reference_routing(workspace: Path) -> dict[str, str]:
    """Return {patient_id: normalized_lab} from the real bulk form."""
    routing: dict[str, str] = {}
    for path in (workspace / "reference_files").glob("*.xlsx"):
        for rows in dio.read_xlsx(path).values():
            hdr = _find_header(rows)
            if not hdr:
                continue
            hi, header = hdr
            lab_i = header.index("Lab Name")
            pid_i = next((j for j, c in enumerate(header) if "Patient ID" in c), None)
            if pid_i is None:
                continue
            for r in rows[hi + 1:]:
                if lab_i < len(r) and pid_i < len(r) and r[lab_i] and r[pid_i] is not None:
                    routing[_norm(r[pid_i])] = _norm(r[lab_i])
    return routing


def _agent_placement(sheets: dict[str, list[list[Any]]], patient_ids: set[str]) -> dict[str, set[str]]:
    """Return {patient_id: set(sheet_labs it appears on)} for known patient ids."""
    placement: dict[str, set[str]] = {}
    for sheet_name, rows in sheets.items():
        lab = _norm(sheet_name)
        for row in rows:
            for cell in row:
                key = _norm(cell)
                if key in patient_ids:
                    placement.setdefault(key, set()).add(lab)
    return placement


def _routing_f1(reference: dict[str, str], placement: dict[str, set[str]]) -> float:
    if not reference:
        return 0.0
    correct = sum(1 for pid, lab in reference.items() if placement.get(pid, set()) == {lab})
    return correct / len(reference)


def _columns_present(sheets: dict[str, list[list[Any]]], required: list[str]) -> float:
    flat = _norm(" ".join(str(c) for rows in sheets.values() for row in rows for c in row))
    return sum(1 for col in required if _norm(col) in flat) / max(1, len(required))


def _deterministic(workspace: Path, deliverable: Path, key: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    sheets = dio.read_xlsx(deliverable)
    reference = _reference_routing(workspace)
    expected_labs = set(reference.values())
    sheet_labs = {_norm(name) for name in sheets}
    placement = _agent_placement(sheets, set(reference))

    checks = {
        "parseable_xlsx": 1.0 if sheets else 0.0,
        "one_sheet_per_lab": (len(expected_labs & sheet_labs) / len(expected_labs)) if expected_labs else 0.0,
        "required_columns": _columns_present(sheets, key.get("required_columns", [])),
        "routing_f1": round(_routing_f1(reference, placement), 4),
    }
    weights = {"parseable_xlsx": 0.10, "one_sheet_per_lab": 0.20, "required_columns": 0.15, "routing_f1": 0.55}
    score = sum(weights[k] * checks[k] for k in weights)
    return score, {"checks": checks, "weights": weights, "score": round(score, 6),
                   "expected_labs": sorted(expected_labs), "sheet_labs": sorted(sheet_labs),
                   "patient_count": len(reference)}


def _reference_context(workspace: Path) -> str:
    parts: list[str] = []
    for path in sorted((workspace / "reference_files").glob("*")):
        if path.suffix.lower() in {".xlsx", ".pdf"}:
            parts.append(f"## {path.name}\n{dio.extract_text(path)}")
    return "\n\n".join(parts)


async def grade(workspace: Path, deliverable: Path, key: dict[str, Any]) -> dict[str, Any]:
    if not deliverable.is_file():
        return {"reward": 0.0, "info": {"status": "missing_deliverable"}}
    det_score, det_detail = _deterministic(workspace, deliverable, key)
    return await native_grading.blend_with_native_judge(
        det_score=det_score,
        det_weight=DET_WEIGHT,
        det_detail=det_detail,
        key=key,
        axis_weights=AXIS_WEIGHTS,
        submitted=dio.extract_text(deliverable)[:50000],
        extra_instruction=(
            "Mis-routed or dropped patients lose factual accuracy and completeness. "
            "Penalize invented patients or accession numbers."
        ),
        reference_context=_reference_context(workspace),
    )
