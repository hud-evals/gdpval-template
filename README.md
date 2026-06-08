# GDPval HUD Template

HUD environment template for GDPval-style knowledge-work evals: stage a frozen
reference bundle, ask the agent for a native deliverable, then grade it with
task-local deterministic checks plus HUD-native LLM judging.

The taskset contains only tasks with authentic GDPval reference files.

## Layout

```text
env.py                       # HUD environment and offline workspace harness
Dockerfile.hud               # Python 3.12 CPU image
pyproject.toml / uv.lock      # uv-managed runtime dependencies
tasks/                       # task packages
  <slug>/task.py             # prompt, metadata, deliverable contract
  <slug>/grader.py           # deterministic checks + HUD-native judge call
  <slug>/reference_files/    # solver-visible reference files
  <slug>/_hidden/rubric.json # local answer key, excluded from image/workspace
deliverable_io.py            # xlsx/pptx/docx/pdf text/structure readers
native_grading.py            # thin adapter around HUD Grade/SubScore/LLMJudgeGrader
```

There is no custom judge transport and no custom rubric engine. Graders compose
HUD native `Grade`, `SubScore`, and `LLMJudgeGrader`. The only local grading
helper is the GDPval-specific fabrication cap on top of those native primitives.

## Tasks

- `acct-afc-audit-sampling`: real GDPval workbook, audit sample `.xlsx`.
- `medsec-pathology-forms`: real GDPval workbook/PDF, per-lab `.xlsx`.

## Use It

```bash
hud deploy .
hud sync tasks <taskset_name>
```

Use `hud sync tasks <taskset_name>` for prompt, grader, rubric, and metadata edits.
Redeploy only when `env.py`, `Dockerfile.hud`, `pyproject.toml`/`uv.lock`,
`deliverable_io.py`, `native_grading.py`, or `reference_files/` files change.