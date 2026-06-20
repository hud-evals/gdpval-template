"""HUD environment for GDPval-style knowledge-work tasks.

Frozen, CPU-only, offline. The harness stages a bundle of reference materials
into the solver workspace, hands the agent a natural-language brief, and on
completion grades a native professional deliverable (.xlsx / .docx / .pptx /
.pdf / code) with a plain, readable grader.

At startup, the harness loads task-local graders and rubrics into memory, then
scrubs evaluator-only authoring files from the deployed image filesystem before
the solver workspace is exposed. On completion it calls
`grade(workspace, deliverable, rubric)` against the fresh deliverable only.
"""

from __future__ import annotations

import inspect
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import types
from pathlib import Path
from typing import Any, AsyncGenerator

APP_ROOT = Path(__file__).resolve().parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))  # so task graders can import local helpers

try:
    from hud import Environment
    from hud.graders import EvaluationResult

    HUD_AVAILABLE = True
except (ImportError, ModuleNotFoundError):  # pragma: no cover - lets env.py import bare
    HUD_AVAILABLE = False

    class Environment:  # type: ignore[no-redef]
        def __init__(self, name: str) -> None:
            self.name = name

        def workspace(self, *_args, **_kwargs):
            return None

        def template(self, *_args, **_kwargs):
            def decorator(func):
                return func

            return decorator


WORKSPACE_DIR = Path(
    os.environ.get("WORKSPACE_DIR", "/workspace/target" if Path("/workspace").exists() else "/tmp/gdpval_workspace")
).resolve()
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

# Stripped from the solver shell so the agent cannot reach the judge or any key.
SOLVER_ENV_DROP_NAMES = {
    "HUD_API_KEY", "HUD_API_URL", "HUD_GATEWAY_URL",
    "GDPVAL_JUDGE_API_KEY", "GDPVAL_JUDGE_BASE_URL",
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
}
SOLVER_ENV_SECRET_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")


ENV_NAME = "gdpval-template"
env = Environment(name="gdpval-template")


def _solver_subprocess_env() -> dict[str, str]:
    clean = dict(os.environ)
    for name in list(clean):
        if name in SOLVER_ENV_DROP_NAMES or any(marker in name for marker in SOLVER_ENV_SECRET_MARKERS):
            clean.pop(name, None)
    clean.update(
        {
            "HOME": "/home/solver" if Path("/home/solver").exists() else str(WORKSPACE_DIR),
            "PATH": f"/app/.venv/bin:{clean.get('PATH', os.defpath)}",
            "VIRTUAL_ENV": "/app/.venv",
            "USER": "solver",
            "LOGNAME": "solver",
            "XDG_CACHE_HOME": str(WORKSPACE_DIR / ".cache"),
            "TMPDIR": "/tmp",
        }
    )
    return clean


def _load_runtime_assets() -> tuple[dict[str, types.ModuleType], dict[str, dict[str, Any]]]:
    """Load evaluator-only grader modules and rubrics before exposing a workspace."""
    graders: dict[str, types.ModuleType] = {}
    rubrics: dict[str, dict[str, Any]] = {}
    for task_dir in sorted((APP_ROOT / "tasks").glob("*")):
        if not task_dir.is_dir():
            continue
        slug = task_dir.name
        grader_path = task_dir / "grader.py"
        if grader_path.is_file():
            spec = importlib.util.spec_from_file_location(f"gdpval_grader_{slug.replace('-', '_')}", grader_path)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"could not load grader at {grader_path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            graders[slug] = module

        rubric_path = task_dir / "_hidden" / "rubric.json"
        if rubric_path.is_file():
            rubrics[slug] = json.loads(rubric_path.read_text(encoding="utf-8"))
    return graders, rubrics


RUNTIME_GRADERS, RUNTIME_RUBRICS = _load_runtime_assets()


def _scrub_runtime_author_files() -> None:
    """Remove grader-only authoring files from the served image filesystem.

    The deployed runtime may run the workspace shell without OS-level bwrap
    isolation, so evaluator-only files must not remain readable under /app.
    Grader modules and rubrics have already been loaded into this process.
    """
    if APP_ROOT != Path("/app"):
        return
    for task_dir in (APP_ROOT / "tasks").glob("*"):
        if not task_dir.is_dir():
            continue
        for path in (
            task_dir / "_hidden",
            task_dir / "__pycache__",
            task_dir / "grader.py",
            task_dir / "task.py",
            task_dir / "build_reference_files.py",
        ):
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                elif path.exists() or path.is_symlink():
                    path.unlink()
            except OSError as exc:  # pragma: no cover
                print(f"[gdpval-env] warning: scrub failed for {path}: {exc}", file=sys.stderr)


_scrub_runtime_author_files()


if HUD_AVAILABLE:
    env.workspace(
        WORKSPACE_DIR,
        name="shell",
        network=False,
        env=_solver_subprocess_env(),
        guest_path=str(WORKSPACE_DIR),
        user="solver",
        track_files=True,
    )


def _chown_solver_workspace() -> None:
    if os.getuid() != 0:
        return
    try:
        subprocess.run(["chown", "-R", "1000:1000", str(WORKSPACE_DIR)], check=True, capture_output=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:  # pragma: no cover
        print(f"[gdpval-env] warning: chown failed: {exc}", file=sys.stderr)


def _prepare_solver_writable_paths(deliverable: Path) -> None:
    """Make expected solver output/cache locations writable across SSH runtimes."""
    root = WORKSPACE_DIR.resolve()
    paths = [WORKSPACE_DIR, deliverable.parent, WORKSPACE_DIR / ".cache"]
    for path in paths:
        try:
            if path != WORKSPACE_DIR:
                try:
                    rel = path.relative_to(WORKSPACE_DIR)
                except ValueError as exc:
                    raise RuntimeError(f"unsafe workspace path: {path}") from exc
                current = WORKSPACE_DIR
                for part in rel.parts:
                    current = current / part
                    if current.is_symlink():
                        current.unlink()
            if path.exists() and not path.is_dir():
                path.unlink()
            path.mkdir(parents=True, exist_ok=True)
            resolved = path.resolve()
            if resolved != root and root not in resolved.parents:
                raise RuntimeError(f"workspace path escapes root: {path}")
            path.chmod(0o777)
        except OSError as exc:  # pragma: no cover
            print(f"[gdpval-env] warning: chmod failed for {path}: {exc}", file=sys.stderr)


def _reset_deliverable_dir(deliverable: Path) -> None:
    """Remove stale outputs from a previous task served by the same process."""
    output_dir = deliverable.parent
    try:
        root = WORKSPACE_DIR.resolve()
        if output_dir != WORKSPACE_DIR:
            rel = output_dir.relative_to(WORKSPACE_DIR)
            current = WORKSPACE_DIR
            for part in rel.parts:
                current = current / part
                if current.is_symlink():
                    current.unlink()
        resolved = output_dir.resolve()
    except OSError:
        return
    except ValueError as exc:
        raise RuntimeError(f"unsafe deliverable path: {deliverable}") from exc
    if resolved == root or root not in resolved.parents:
        return
    if output_dir.is_symlink() or output_dir.is_file():
        output_dir.unlink()
    elif output_dir.exists():
        shutil.rmtree(output_dir)


def _deliverable_path(path_text: str) -> Path:
    rel = Path(path_text or "deliverable/report.md")
    if rel.is_absolute() or ".." in rel.parts:
        raise RuntimeError(f"unsafe deliverable path: {path_text!r}")
    return WORKSPACE_DIR / rel


# Scratch dirs a confused agent may use instead of the workspace. These are listed
# only in diagnostics (never graded) so a human can see *where* a misplaced
# deliverable went without risking a false positive from a stale/cross-run file.
SCRATCH_ROOTS = ("/tmp", "/home/solver", "/root")
_WALK_SKIP_DIRS = {".git", "__pycache__", ".cache", ".config", ".ipython",
                   "node_modules", ".npm", "reference_files"}


def _within(root: Path, path: Path) -> bool:
    try:
        rp, rr = path.resolve(), root.resolve()
    except OSError:
        return False
    return rp == rr or rr in rp.parents


def _display(path: Path) -> str:
    """Workspace-relative path when possible, otherwise the absolute path."""
    try:
        return str(path.resolve().relative_to(WORKSPACE_DIR.resolve()))
    except ValueError:
        return str(path.resolve())


def _solver_files(root: Path, limit: int = 4000) -> list[Path]:
    """Non-reference files under ``root`` (the solver's outputs)."""
    reference_root = (WORKSPACE_DIR / "reference_files").resolve()
    out: list[Path] = []
    seen: set[Path] = set()
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _WALK_SKIP_DIRS]
            for name in filenames:
                path = Path(dirpath) / name
                try:
                    if path.is_symlink() or not path.is_file():  # skip symlinks, sockets, fifos
                        continue
                    resolved = path.resolve()
                except OSError:
                    continue
                if resolved in seen:
                    continue
                if resolved == reference_root or reference_root in resolved.parents:
                    continue
                seen.add(resolved)
                out.append(path)
                if len(out) >= limit:
                    return out
    except OSError:
        pass
    return out


def _misplaced_files(suffix: str) -> list[str]:
    """Deliverable-type files found in scratch dirs (e.g. agent wrote the .xlsx to
    /tmp). Diagnostics only, never graded; filtered to the deliverable's file type
    to stay signal-rich."""
    suffix = suffix.lower()
    found: list[str] = []
    for candidate in SCRATCH_ROOTS:
        rp = Path(candidate)
        if not rp.exists() or _within(WORKSPACE_DIR, rp):
            continue
        found.extend(
            str(p) for p in _solver_files(rp, limit=200)
            if (not suffix) or p.suffix.lower() == suffix
        )
    return found[:40]


def _resolve_deliverable(expected: Path, task_started_at: float) -> tuple[Path | None, dict[str, Any]]:
    """Resolve the agent's deliverable within the workspace, tolerating small naming
    slips, without forgiving genuinely missing work. Grading is scoped to fresh
    files in the expected output directory only; elsewhere is diagnostic-only."""
    fresh_cutoff = task_started_at - 1.0

    def is_fresh(path: Path) -> bool:
        try:
            return path.stat().st_mtime >= fresh_cutoff
        except OSError:
            return False

    if expected.is_file() and not expected.is_symlink() and is_fresh(expected):
        return expected, {}

    expected_name = expected.name.lower()
    expected_stem = expected.stem.lower()
    expected_suffix = expected.suffix.lower()
    files = [path for path in _solver_files(expected.parent) if is_fresh(path)]
    same_suffix = [path for path in files if path.suffix.lower() == expected_suffix]

    def pick(matches: list[Path]) -> Path | None:
        if len(matches) == 1:
            return matches[0]
        if not matches:
            return None
        try:
            return max(matches, key=lambda p: p.stat().st_mtime)
        except OSError:
            return matches[0]

    def found(path: Path) -> tuple[Path, dict[str, Any]]:
        return path, {"deliverable_resolved_from": _display(path), "expected_deliverable": _display(expected)}

    name_match = pick([p for p in same_suffix if p.name.lower() == expected_name])
    if name_match is not None:
        return found(name_match)

    stem_match = pick([
        p for p in same_suffix
        if expected_stem in p.stem.lower() or p.stem.lower() in expected_stem
    ])
    if stem_match is not None:
        return found(stem_match)

    if len(same_suffix) == 1:
        return found(same_suffix[0])

    return None, {
        "expected_deliverable": _display(expected),
        "candidate_deliverables": [_display(path) for path in same_suffix[:20]],
        "workspace_files": [_display(path) for path in _solver_files(WORKSPACE_DIR)[:80]],
        "misplaced_files_outside_workspace": _misplaced_files(expected_suffix),
    }


def _zero(status: str, **info: Any) -> dict[str, Any]:
    return {"reward": 0.0, "info": {"status": status, **info}}


def _workspace_preamble(deliverable_rel: str) -> str:
    """Factual environment contract prepended to every task prompt.

    States only *where* things live — the working directory, the staged input
    directory, and the absolute deliverable path — the same context a real analyst
    is given. It deliberately does not coach navigation or warn against fabrication:
    if an agent ignores the stated paths or invents data, that is a genuine failure
    and should score accordingly. The grader still only reads the workspace.
    """
    ws = str(WORKSPACE_DIR)
    deliverable_abs = str((WORKSPACE_DIR / deliverable_rel))
    return (
        "[Environment]\n"
        f"- Working directory: {ws}\n"
        f"- Reference files for this task are staged at: {ws}/reference_files/\n"
        f"- Save your deliverable to: {deliverable_abs}\n\n"
    )


def _stage_bundle(task_slug: str) -> None:
    """Copy tasks/<slug>/reference_files/ into the workspace. The _hidden/ key is never copied."""
    source = APP_ROOT / "tasks" / task_slug / "reference_files"
    if not source.is_dir():
        raise RuntimeError(f"no reference files staged for task {task_slug!r} at {source}")
    target = WORKSPACE_DIR / "reference_files"
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(".gitkeep"))


def _load_grader(task_slug: str):
    """Load the task-local grader from the evaluator image, never from task args."""
    try:
        return RUNTIME_GRADERS[task_slug]
    except KeyError as exc:
        raise RuntimeError(f"no grader loaded for task {task_slug!r}") from exc


def _load_rubric(task_slug: str) -> dict[str, Any] | None:
    return RUNTIME_RUBRICS.get(task_slug)


async def _grade(task_slug: str, deliverable: Path) -> dict[str, Any]:
    grader = _load_grader(task_slug)
    rubric = _load_rubric(task_slug)
    if not rubric:
        return _zero("missing_rubric")
    result = grader.grade(WORKSPACE_DIR, deliverable, rubric)
    if inspect.isawaitable(result):
        result = await result
    return result if isinstance(result, dict) and "reward" in result else _zero("invalid_grader_result")


def _to_eval(result: dict[str, Any]) -> Any:
    """Wrap a grader dict in an EvaluationResult (the current HUD second-yield type)."""
    info = result.get("info", {}) if isinstance(result.get("info"), dict) else {}
    status = str(info.get("status", "ok"))
    reward = float(result.get("reward", 0.0))
    if not HUD_AVAILABLE:  # bare import / local tests
        return result
    return EvaluationResult(
        reward=reward,
        done=True,
        content=f"status={status} reward={reward:.3f}",
        info=info,
        isError=status in ("grader_error", "invalid_grader_result"),
    )


async def _run(task_slug: str, prompt: str, deliverable_rel: str) -> AsyncGenerator[Any, None]:
    if not task_slug:
        raise RuntimeError("task args must include task_slug")
    deliverable = _deliverable_path(deliverable_rel)
    _reset_deliverable_dir(deliverable)
    _stage_bundle(task_slug)
    _chown_solver_workspace()
    _prepare_solver_writable_paths(deliverable)
    task_started_at = time.time()

    _ = yield _workspace_preamble(deliverable_rel) + prompt

    resolved_deliverable, resolution_info = _resolve_deliverable(deliverable, task_started_at)
    if resolved_deliverable is None:
        yield _to_eval(_zero("missing_deliverable", **resolution_info))
        return
    try:
        result = await _grade(task_slug, resolved_deliverable)
        if resolution_info:
            result.setdefault("info", {}).update(resolution_info)
        yield _to_eval(result)
    except Exception as exc:  # pragma: no cover - surfaces author errors
        yield _to_eval(_zero("grader_error", reason=repr(exc)[:500]))


@env.template(id="gdpval_task")
async def gdpval_task(
    prompt: str = "Read the staged reference_files and produce the requested deliverable.",
    task_slug: str = "",
    deliverable: str = "deliverable/report.md",
) -> AsyncGenerator[Any, None]:
    async for item in _run(task_slug, prompt, deliverable):
        yield item
