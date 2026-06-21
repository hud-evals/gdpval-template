"""Task registry for the GDPval knowledge-work template.

Each task is a package under tasks/<slug>/:
  task.py            -- brief, deliverable contract, source GDPval task_id
  grader.py          -- plain readable grader (deterministic axis + LLM-judge axis)
  build_reference_files.py -- verifies the solver-visible reference files
  reference_files/   -- staged mixed-format reference files
  _hidden/rubric.json -- plain JSON answer key, read here and excluded from the image

Each task row is minted by calling the env.py ``gdpval_task`` template with the
task's args, grader source, and rubric (the rubric never enters the image).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REQUIRED_AXES = {
    "factual_accuracy",
    "professional_judgment",
    "evidence_grounding",
    "completeness",
    "format_regulatory_compliance",
    "clarity",
}


def _load_task_module(slug: str):
    task_py = ROOT / slug / "task.py"
    spec = importlib.util.spec_from_file_location(f"_gdpval_task_{slug.replace('-', '_')}", task_py)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load task module for {slug}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _validate_rubric(slug: str, rubric: dict[str, Any]) -> None:
    missing = [
        key
        for key in ("correct_analysis", "do_not_overreward", "axis_definitions", "llm_judge_reference")
        if not rubric.get(key)
    ]
    if missing:
        raise RuntimeError(f"{slug}: rubric missing required keys: {', '.join(missing)}")

    axes = rubric.get("axis_definitions")
    if not isinstance(axes, dict):
        raise RuntimeError(f"{slug}: axis_definitions must be an object")
    missing_axes = sorted(REQUIRED_AXES - set(axes))
    if missing_axes:
        raise RuntimeError(f"{slug}: rubric missing axis definitions: {', '.join(missing_axes)}")

    judge_ref = rubric.get("llm_judge_reference")
    if not isinstance(judge_ref, dict):
        raise RuntimeError(f"{slug}: llm_judge_reference must be an object")
    for key in ("task_goal", "hidden_reference", "credit", "penalize"):
        if not judge_ref.get(key):
            raise RuntimeError(f"{slug}: llm_judge_reference missing {key!r}")


def _build_one(slug: str):
    from env import gdpval_task  # the template factory mints one Task per call

    mod = _load_task_module(slug)
    grader_source = (ROOT / slug / "grader.py").read_text(encoding="utf-8")
    rubric_path = ROOT / slug / "_hidden" / "rubric.json"
    if not rubric_path.is_file():
        raise RuntimeError(f"{slug}: missing rubric at {rubric_path}")
    rubric: dict[str, Any] = json.loads(rubric_path.read_text(encoding="utf-8"))
    _validate_rubric(slug, rubric)

    task = gdpval_task(**mod.TASK_ARGS, grader_source=grader_source, rubric=rubric)
    task.slug = mod.TASK_SLUG
    task.columns = dict(mod.METADATA)  # filterable leaderboard facets
    return task


def build_tasks() -> list:
    slugs = [task_py.parent.name for task_py in sorted(ROOT.glob("*/task.py"))]
    if not slugs:
        raise RuntimeError("no GDPval tasks found under tasks/")
    return [_build_one(slug) for slug in slugs]


def load_task(slug: str):
    return _load_task_module(slug)


TASK_SLUGS: list[str] = sorted(path.parent.name for path in ROOT.glob("*/task.py"))
tasks = build_tasks()
task_ids = [task.slug for task in tasks]
