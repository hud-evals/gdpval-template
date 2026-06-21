"""Thin HUD-native grading helpers used by task-local graders."""

from __future__ import annotations

import os
from typing import Any

from hud.graders import LLMJudgeGrader, SubScore, _combine_subscores

FABRICATION_CAP = 0.30
DEFAULT_MODEL = "claude-haiku-4-5"


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
) -> dict[str, Any]:
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
            name="llm_judge",
            value=0.0,
            weight=llm_weight,
            metadata={"status": "no_hud_api_key"},
        )
        result = _combine_subscores([det_subscore, missing_judge])
        return _as_dict(result, status="det_only:no_hud_api_key", deterministic=det_detail)

    quality = await LLMJudgeGrader.grade(
        name="llm_judge",
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
    # `combine` only does a normalized weighted sum, so the hard cap is applied by hand below.
    result = _combine_subscores([det_subscore, quality, fabrication_guard])
    final_reward = float(result.reward)
    fabrication_capped = fabrication_guard.value < 0.5 and final_reward > FABRICATION_CAP
    if fabrication_capped:
        final_reward = FABRICATION_CAP

    out = _as_dict(result, status="ok", deterministic=det_detail)
    out["reward"] = round(final_reward, 6)
    out["info"]["fabrication_capped"] = fabrication_capped
    return out


def _strip_parameters(info: dict[str, Any]) -> dict[str, Any]:
    # Each subscore's metadata carries the SDK judge's `_parameters` — the full
    # answer + criteria, echoed back. Drop it: the result is framed as one JSON line
    # over the control channel (64KB limit), and a large deliverable blows past it.
    return {
        name: ({k: v for k, v in meta.items() if k != "_parameters"} if isinstance(meta, dict) else meta)
        for name, meta in (info or {}).items()
    }


def _as_dict(result, *, status: str, deterministic: dict[str, Any]) -> dict[str, Any]:
    return {
        "reward": round(float(result.reward), 6),
        "info": {
            "status": status,
            "deterministic": deterministic,
            "subscores": [item.model_dump() for item in (result.subscores or [])],
            "native_grading_info": _strip_parameters(result.info),
        },
    }
