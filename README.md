# GDPval HUD Template

HUD v6 environment template for GDPval-style knowledge-work evals: stage a frozen
reference bundle, ask the agent for a native deliverable, then grade it with
task-local deterministic checks plus HUD-native LLM judging.

The taskset contains only tasks with authentic GDPval reference files.

## Layout

```text
env.py                       # HUD v6 environment, template, and workspace capability
Dockerfile.hud               # Python 3.12 CPU image
pyproject.toml / uv.lock      # uv-managed runtime dependencies
tasks/                       # task packages
  <slug>/task.py             # prompt, columns metadata, deliverable contract
  <slug>/grader.py           # deterministic checks + HUD-native judge call
  <slug>/reference_files/    # solver-visible reference files
  <slug>/_hidden/rubric.json # evaluator-only answer key, scrubbed at runtime
deliverable_io.py            # xlsx/pptx/docx/pdf text/structure readers
native_grading.py            # thin adapter around HUD SubScore/LLMJudgeGrader
```

There is no custom judge transport and no custom rubric engine. Graders compose
HUD native `SubScore`, `EvaluationResult`, and `LLMJudgeGrader` via `combine`.
The only local grading helper is the GDPval-specific fabrication cap on top of
those native primitives.

## Tasks

- `acct-afc-audit-sampling`: real GDPval workbook, audit sample `.xlsx`.
- `medsec-pathology-forms`: real GDPval workbook/PDF, per-lab `.xlsx`.

## Use It

```bash
hud eval tasks.py <model>
hud deploy .
hud sync tasks <taskset_name>
```

Use `hud eval tasks.py <model>` for local iteration. Use
`hud sync tasks <taskset_name>` for prompt and metadata edits.
Redeploy only when `env.py`, `Dockerfile.hud`, `pyproject.toml`/`uv.lock`,
`deliverable_io.py`, `native_grading.py`, `tasks/<slug>/grader.py`,
`tasks/<slug>/_hidden/rubric.json`, or `reference_files/` files change.

The solver acts through a v6 workspace (`ssh`) capability rooted at
`WORKSPACE_DIR`. `Dockerfile.hud` installs `bubblewrap`, which HUD uses for SSH
session isolation. Hosted jobs must run on a runtime path that permits the
required namespace operations; otherwise shell startup can fail with a
`bwrap: No permissions to create new namespace` error. Solver credentials are
still stripped from the workspace environment. As defense in depth, `env.py`
preloads grader modules and rubrics into the evaluator process and then removes
`_hidden/`, grader source, task source, and task build scripts from `/app`
before the workspace shell is exposed. Spreadsheet and document libraries are
installed into system Python as well as the app venv so agent shell commands
like `python3 -c "import openpyxl"` work offline. The workspace setup also makes
expected output directories writable by the solver. The image serves the v6
control channel with `hud serve env.py --host 0.0.0.0`.

Task rows intentionally contain only prompt, task slug, and deliverable path.
Graders and rubrics are loaded inside the evaluator image so answer keys do not
appear in task args, task listings, prompts, or the served `/app` filesystem
after environment startup.
