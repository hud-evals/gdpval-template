"""Thin HUD-native grading helpers used by task-local graders."""

from __future__ import annotations

import os
from typing import Any

from hud.graders import EvaluationResult, LLMJudgeGrader, SubScore, _combine_subscores

FABRICATION_CAP = 0.30
DEFAULT_MODEL = "claude-haiku-4-5"


def zero_result(status: str, **info: Any) -> EvaluationResult:
    return EvaluationResult(
        reward=0.0,
        content=f"status={status} reward=0.000",
        info={"status": status, **info},
    )


def judge_available() -> bool:
    # The judge uses the HUD gateway via settings.api_key, so check that, not the env var.
    from hud.settings import settings

    return bool(getattr(settings, "api_key", None))


def criteria_from_key(key: dict[str, Any], axis_weights: dict[str, float], extra_instruction: str) -> list[tuple[str, float]]:
    axis_definitions = key.get("axis_definitions", {})
    reference = key.get("llm_judge_reference", {})
    correct = key.get("correct_analysis", "")
    avoid = "; ".join(str(item) for item in key.get("do_not_overreward", []))
    criteria: list[tuple[str, float]] = []
    for axis, weight in axis_weights.items():
        definition = axis_definitions.get(axis, axis.replace("_", " "))
        criteria.append(
            (
                (
                    f"{axis}: {definition}. Grade strictly against the hidden reference: "
                    f"{reference.get('hidden_reference', correct)}. Do not overreward: {avoid}. "
                    f"{extra_instruction} If a REFERENCE MATERIAL section is present, use it as the source of truth."
                ),
                weight,
            )
        )
    return criteria


async def blend_with_native_judge(
    *,
    det_score: float,
    det_weight: float,
    det_detail: dict[str, Any],
    key: dict[str, Any],
    axis_weights: dict[str, float],
    submitted: str,
    extra_instruction: str,
    reference_context: str = "",
) -> EvaluationResult:
    det_subscore = SubScore(
        name="deterministic",
        value=max(0.0, min(1.0, float(det_score))),
        weight=det_weight,
        metadata=det_detail,
    )
    llm_weight = max(0.0, 1.0 - det_weight)
    model = os.environ.get("GDPVAL_JUDGE_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    question = key.get("llm_judge_reference", {}).get("task_goal", "Grade this GDPval deliverable.")
    judged_answer = submitted
    if reference_context.strip():
        judged_answer = (
            "REFERENCE MATERIAL:\n"
            f"{reference_context[:60000]}\n\n"
            "SUBMITTED DELIVERABLE:\n"
            f"{submitted}"
        )

    if not judge_available():
        missing_judge = SubScore(
            name="LLMJudgeGrader",
            value=0.0,
            weight=llm_weight,
            metadata={"status": "no_hud_api_key"},
        )
        result = _combine_subscores([det_subscore, missing_judge])
        return _finalize(result, status="det_only:no_hud_api_key")

    quality = await LLMJudgeGrader.grade(
        weight=llm_weight,
        answer=judged_answer,
        question=question,
        criteria=criteria_from_key(key, axis_weights, extra_instruction),
        model=model,
    )
    fabrication_guard = await LLMJudgeGrader.grade(
        name="fabrication_guard",
        weight=0.0,
        answer=judged_answer,
        question=question,
        criteria=[
            (
                "The submission must not invent names, figures, citations, authorities, patients, "
                "companies, sample rules, or benchmark values absent from the staged reference bundle. "
                "Use the REFERENCE MATERIAL section as the source of truth. Return MET only when all "
                "material claims in SUBMITTED DELIVERABLE are grounded in the reference material; return "
                "UNMET for any substantive unsupported fabrication. Do not treat derived calculations, "
                "standard statistical formulas, or explicitly labeled professional judgment based on the "
                "reference material as fabrication.",
                1.0,
            )
        ],
        model=model,
    )
    result = _combine_subscores([det_subscore, quality, fabrication_guard])
    fabrication_capped = fabrication_guard.value < 0.5 and result.reward > FABRICATION_CAP
    if fabrication_capped:
        cap_penalty = SubScore(
            name="fabrication_cap",
            value=1.0,
            weight=FABRICATION_CAP - result.reward,
            info={"reason": "Fabrication guard failed; final reward capped."},
        )
        result = _combine_subscores([*(result.subscores or []), cap_penalty])

    return _finalize(result, status="ok", fabrication_capped=fabrication_capped)


def _strip_subscore_parameters(subscore: SubScore) -> SubScore:
    """Remove oversized grader inputs while preserving the native score tree."""
    info = dict(subscore.info or {})
    info.pop("_parameters", None)
    children = (
        [_strip_subscore_parameters(child) for child in subscore.children]
        if subscore.children
        else None
    )
    return subscore.model_copy(update={"info": info or None, "children": children})


def _finalize(
    result: EvaluationResult,
    *,
    status: str,
    fabrication_capped: bool = False,
) -> EvaluationResult:
    subscores = [
        _strip_subscore_parameters(subscore) for subscore in (result.subscores or [])
    ]
    info = {**result.info, "status": status}
    if status == "ok":
        info["fabrication_capped"] = fabrication_capped
    return result.model_copy(
        update={
            "reward": round(float(result.reward), 6),
            "content": f"status={status} reward={result.reward:.3f}",
            "info": info,
            "subscores": subscores,
        }
    )
