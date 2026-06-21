# GDPval HUD Template

A HUD v6 environment for GDPval-style knowledge-work evals. The agent gets an
`ssh` workspace and a colleague brief, reads a staged bundle of authentic GDPval
reference files, and writes a native deliverable (`.xlsx` / `.docx` / `.pptx` /
`.pdf`). Each deliverable is graded by task-local deterministic checks blended
with an LLM judge, plus a fabrication cap.

## Layout

```text
env.py             # Environment + the gdpval_task template + the offline workspace harness
Dockerfile.hud     # Python 3.12 CPU image, served on the control channel
pyproject.toml     # deps (hud-python[agents] >= 0.6) + uv.lock
tasks.py           # public `tasks` list + re-exported `env` — the loader entrypoint
tasks/<slug>/
  task.py          # prompt, metadata, deliverable contract
  grader.py        # deterministic checks + the LLM-judge call
  reference_files/ # solver-visible reference files
  _hidden/rubric.json   # answer key — passed as a task arg, never baked into the image
deliverable_io.py  # xlsx/pptx/docx/pdf readers
native_grading.py  # adapter over hud.graders + the fabrication cap
```

## How it works

- The agent works in an `ssh` Workspace rooted at the solver workspace. That shell
  runs as a non-root uid with every secret stripped from its environment, so it
  can't read the grading key or call the judge.
- Each task is the `gdpval_task` template, minted per slug in `tasks/__init__.py`.
  The grader source and rubric travel as task args — the rubric (answer key) is
  never baked into the deployed image.
- Grading blends a deterministic axis (parse the deliverable, check structure)
  with a weighted-axis LLM judge, plus a fabrication guard that caps the reward if
  the deliverable invents data not in the reference bundle.

Offline is enforced at the platform layer, not in the env: without bubblewrap,
`network=False` is not an air-gap, so the env-side guard is the secret strip.

## Run it

Locally (serves the env from source, no deploy):

```bash
uv sync
hud eval tasks.py claude          # one agent rollout against the env
```

On the platform — the LLM judge runs inside the env container, so it needs a key.
Put `HUD_API_KEY` in `.env` (`hud deploy` loads it automatically):

```bash
cp .env.example .env              # set HUD_API_KEY

hud deploy .                      # build + deploy the env image on HUD
hud sync tasks <taskset>          # push the tasks to a platform taskset
hud eval tasks.py claude --runtime hud   # run an agent against the deployed env
```

Use `hud sync tasks` for prompt / grader / rubric / metadata edits. Redeploy only
when `env.py`, `Dockerfile.hud`, `pyproject.toml` / `uv.lock`, `deliverable_io.py`,
`native_grading.py`, or a `reference_files/` bundle changes.

## Testing

```bash
uv run pytest tests/ -q
```
