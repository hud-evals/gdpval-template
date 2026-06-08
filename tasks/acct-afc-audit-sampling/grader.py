"""Grader — acct-afc-audit-sampling. Plain, readable. Tuned to the REAL GDPval file.

Real reference file `Population v2.xlsx` columns:
  No | Division | Sub-Division | Country | Legal Entity | KRIs | Q3 2024 KRI | Q2 2024 KRI
(1,516 rows). There is no A1/C1 metric code or product column, so selection is
genuinely judgmental — GDPval itself grades this with human experts. The
deterministic axis therefore checks *defensible* sampling structure rather than
an exact set: every flagged row must meet a documented risk criterion
(precision), the sample must be a real subset (not the whole population), it must
span multiple divisions/countries (coverage), and the workings (sample size,
variance) must be present. The LLM-judge axis covers sizing and overall quality.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import deliverable_io as dio
import native_grading

DET_WEIGHT = 0.45
AXIS_WEIGHTS = {
    "factual_accuracy": 0.24,
    "professional_judgment": 0.26,
    "evidence_grounding": 0.18,
    "completeness": 0.14,
    "format_regulatory_compliance": 0.10,
    "clarity": 0.08,
}


def _to_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _norm_id(v: Any) -> str:
    """Canonical row identifier, tolerant of int/float round-tripping (3 == 3.0)."""
    f = _to_float(v)
    if f is not None and f == int(f):
        return str(int(f))
    return str(v).strip()


def _meets_criterion(row: dict[str, Any], crit: dict[str, Any]) -> bool:
    country = str(row.get("Country", "")).strip()
    q3, q2 = _to_float(row.get("Q3 2024 KRI")), _to_float(row.get("Q2 2024 KRI"))
    zero = (q3 == 0) or (q2 == 0)
    variance = None if (q2 in (None, 0)) else (q3 - q2) / q2 if q3 is not None else None
    return (
        country in crit.get("high_risk_countries", [])
        or (crit.get("zero_value_selects") and zero)
        or (variance is not None and abs(variance) > crit.get("variance_threshold", 0.20))
        or str(row.get("Legal Entity", "")).strip() in crit.get("past_issue_entities", [])
    )


def _population(workspace: Path) -> dict[str, dict[str, Any]]:
    """Index the real population by its 'No' identifier."""
    for path in (workspace / "reference_files").glob("*.xlsx"):
        for rows in dio.read_xlsx(path).values():
            if not rows:
                continue
            header = [str(c).strip() if c is not None else "" for c in rows[0]]
            if "Country" in header and any("KRI" in h for h in header):
                out: dict[str, dict[str, Any]] = {}
                for r in rows[1:]:
                    rec = dict(zip(header, r))
                    key = _norm_id(rec.get("No", ""))
                    if key:
                        out[key] = rec
                return out
    return {}


def _selected_rows(deliverable_sheets: dict[str, list[list[Any]]], population: dict[str, dict[str, Any]]) -> list[str]:
    """'No' identifiers the agent placed in the sample (any sheet whose rows carry a known No)."""
    selected: list[str] = []
    for rows in deliverable_sheets.values():
        if not rows:
            continue
        header = [str(c).strip() if c is not None else "" for c in rows[0]]
        no_i = header.index("No") if "No" in header else 0
        for r in rows[1:]:
            if no_i < len(r) and r[no_i] is not None:
                key = _norm_id(r[no_i])
                if key in population:
                    selected.append(key)
    return selected


def _deterministic(workspace: Path, deliverable: Path, key: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    sheets = dio.read_xlsx(deliverable)
    text = dio.extract_text(deliverable).lower()
    population = _population(workspace)
    crit = key.get("selection_criteria", {})

    selected = _selected_rows(sheets, population)
    n_pop = len(population)
    n_sel = len(set(selected))
    meeting = [s for s in set(selected) if _meets_criterion(population[s], crit)]
    precision = len(meeting) / n_sel if n_sel else 0.0
    divisions = {str(population[s].get("Division", "")).strip() for s in set(selected)}
    countries = {str(population[s].get("Country", "")).strip() for s in set(selected)}

    lo, hi = key.get("sample_size_expectation", {}).get("plausible_n_range", [15, 200])
    checks = {
        "parseable_xlsx": 1.0 if sheets else 0.0,
        "sample_size_tab": 1.0 if any("sample size" in s.lower() for s in sheets) or "sample size" in text else 0.0,
        "variance_present": 1.0 if "variance" in text else 0.0,
        "selection_precision": round(precision, 4),
        "is_a_sample_not_whole_population": 1.0 if (n_pop and 0 < n_sel <= 0.5 * n_pop) else 0.0,
        "coverage": 1.0 if (len(divisions) >= 3 and len(countries) >= 3) else 0.0,
        "plausible_sample_size": 1.0 if (lo <= n_sel <= hi) else (0.5 if n_sel else 0.0),
    }
    weights = {"parseable_xlsx": 0.08, "sample_size_tab": 0.12, "variance_present": 0.12,
               "selection_precision": 0.35, "is_a_sample_not_whole_population": 0.13,
               "coverage": 0.10, "plausible_sample_size": 0.10}
    score = sum(weights[k] * checks[k] for k in weights)
    return score, {"checks": checks, "weights": weights, "score": round(score, 6),
                   "population_size": n_pop, "selected_size": n_sel,
                   "selected_meeting_criterion": len(meeting),
                   "divisions_covered": sorted(d for d in divisions if d),
                   "countries_covered": sorted(c for c in countries if c)}


def _reference_context(workspace: Path, deliverable: Path, det_detail: dict[str, Any], key: dict[str, Any]) -> str:
    """Give the judge the exact source rows the agent selected.

    The full population is too large for judge context; passing only a prefix can
    make valid high-row-number selections look fabricated. Deterministic checks
    already verify the selected IDs against the full workbook, so the judge only
    needs the selected source records and the allowed risk criteria.
    """
    population = _population(workspace)
    selected = sorted(set(_selected_rows(dio.read_xlsx(deliverable), population)), key=lambda item: int(item))
    source_rows = [population[item] for item in selected if item in population]
    criteria = key.get("selection_criteria", {})
    return "\n\n".join(
        [
            f"## Deterministic grounding diagnostics\n{det_detail}",
            f"## Allowed risk criteria from rubric\n{criteria}",
            "## Selected source rows from original Population v2.xlsx\n"
            + "\n".join(str(row) for row in source_rows),
            (
                "## Judge note\n"
                "Treat standard sampling formulas, derived variance calculations, derived risk scores, "
                "and selection rationale based on the listed risk criteria as analysis, not fabrication. "
                "Fabrication means inventing source rows, entities, countries, KRI values, or unsupported "
                "external authorities."
            ),
        ]
    )


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
            "The sample-size method is the author's choice if documented and consistent. "
            "Selecting the whole population or rows that meet no risk criterion is not top-band. "
            "Penalize invented sample-size rules or figures."
        ),
        reference_context=_reference_context(workspace, deliverable, det_detail, key),
    )
