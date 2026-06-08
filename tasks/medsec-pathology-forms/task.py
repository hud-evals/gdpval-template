"""Ported GDPval task — Medical Secretaries & Administrative Assistants (Health Care & Social Assistance).

Source: openai/gdpval gold subset, task_id a0552909-bc66-4a3a-8970-ee0d17b49718
("lead medical secretary at an oncology testing center; split the month's bulk
test order into a separate Excel sheet for each pathology lab").

Brief restated in colleague-brief style; the routing task, the reference bulk
form, and the per-lab Excel deliverable match the source task.
"""

from __future__ import annotations

GDPVAL_TASK_ID = "a0552909-bc66-4a3a-8970-ee0d17b49718"
TASK_SLUG = "medsec-pathology-forms"
DELIVERABLE = "deliverable/pathology_bulk_forms.xlsx"

PROMPT = """You're the lead medical secretary at Reach Oncology and it's time to send the
July 2025 bulk pathology orders out. `reference_files/July 2025 - Bulk Form Needed.xlsx`
lists every patient we need to submit this month, and each row says which lab it goes to.
Our logo is in `reference_files/REACH LOGO.pdf`.

Our three labs each want their own form, so please build me one workbook,
`deliverable/pathology_bulk_forms.xlsx`, with a separate sheet for each lab (name each
sheet after the lab). On each lab's sheet, list only that lab's patients with their patient
ID, first and last name, date of birth, pathology accession number, and request sent date,
and put a clear header at the top with the lab name and the order month. Don't mix patients
between labs — each patient must end up on exactly the right lab's sheet.
"""

GRADER_CONFIG = {
    "axes": ["factual_accuracy", "professional_judgment", "evidence_grounding",
             "completeness", "format_regulatory_compliance", "clarity"],
    "det_weight": 0.55,
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
            "occupation": "Medical Secretaries and Administrative Assistants",
            "sector": "Health Care and Social Assistance",
            "deliverable_format": "xlsx",
            "bundle_status": "authentic_gdpval_reference_files",
            "grader_det_weight": GRADER_CONFIG["det_weight"],
            "primary_failure_mode": "mis-routed tests between lab sheets / missing required columns",
        },
    )
