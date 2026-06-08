"""Ported GDPval task — Accountants & Auditors (Professional, Scientific & Technical Services).

Source: openai/gdpval gold subset, task_id 83d10b06-26d1-4636-a32c-23f92c57f30b
("review and test accuracy of reported Anti-Financial-Crime risk metrics; size a
sample, run variance analysis, and select the audit sample").

The brief below is restated in colleague-brief style; the assignment, the
reference spreadsheet, and the deliverable format match the source task.
"""

from __future__ import annotations

GDPVAL_TASK_ID = "83d10b06-26d1-4636-a32c-23f92c57f30b"
TASK_SLUG = "acct-afc-audit-sampling"
DELIVERABLE = "deliverable/Sample.xlsx"

PROMPT = """You're on the internal audit team and we need to test the accuracy of the
Anti-Financial-Crime (AFC) risk metrics the first line reported for Q2 and Q3 2024. The
population is in `reference_files/Population v2.xlsx` — one row per reported KRI, with the
Division, Sub-Division, Country, Legal Entity, KRI name, and the Q3 and Q2 2024 values.

Please work it up and hand me back a new workbook saved as `deliverable/Sample.xlsx`:

1. Add a "Sample Size Calculation" tab documenting the required sample size for testing at a
   90% confidence level with a 10% tolerable error rate — show your workings, not just the
   number.
2. Compute the quarter-on-quarter variance for each KRI.
3. Select a risk-based audit sample. Prioritise the risky items: KRIs with more than 20%
   QoQ variance, any zero-value rows, and our high-risk jurisdictions (Cayman Islands,
   Pakistan, the UAE), and make sure every Division and Sub-Division is represented. Keep it
   to a defensible sample, not the whole risky population.
4. Put the selected rows into the `Sample.xlsx` workbook, keep the row identifier (the "No"
   column) so each selection traces back to the population, and flag the selected rows.

Keep it defensible — I need to be able to explain why each row was pulled.
"""

GRADER_CONFIG = {
    "axes": ["factual_accuracy", "professional_judgment", "evidence_grounding",
             "completeness", "format_regulatory_compliance", "clarity"],
    "det_weight": 0.50,
    "deliverable": DELIVERABLE,
}

TASK_ARGS = {"prompt": PROMPT, "task_slug": TASK_SLUG, "deliverable": DELIVERABLE}


def build_task():
    from hud.eval.task import Task

    return Task(
        env={"name": "gdpval-template"},
        scenario="gdpval_task",
        slug=TASK_SLUG,
        args=TASK_ARGS,
        metadata={
            "gdpval_task_id": GDPVAL_TASK_ID,
            "occupation": "Accountants and Auditors",
            "sector": "Professional, Scientific, and Technical Services",
            "deliverable_format": "xlsx",
            "bundle_status": "authentic_gdpval_reference_file",
            "grader_det_weight": GRADER_CONFIG["det_weight"],
            "primary_failure_mode": "incomplete/incorrect risk-based sample selection",
        },
    )
