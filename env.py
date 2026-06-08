"""HUD environment for GDPval-style knowledge-work tasks.

Frozen, CPU-only, offline. The harness stages a bundle of reference materials
into the solver workspace, hands the agent a natural-language brief, and on
completion grades a native professional deliverable (.xlsx / .docx / .pptx /
.pdf / code) with a plain, readable grader.

Grading is fully transparent: there is no sealing or encryption. On completion
the harness loads grader/rubric from plaintext task args produced by `tasks/`
and calls `grade(workspace, deliverable, rubric)`. The author-local `_hidden/`
directory is deliberately excluded from the deployed image and from the solver
workspace; it is a source file for task sync, not runtime state.
"""

from __future__ import annotations

import asyncio
import inspect
import importlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tomllib
import types
from pathlib import Path
from typing import Any, AsyncGenerator, Literal

EditCommand = Literal["view", "create", "str_replace", "insert", "undo_edit"]

APP_ROOT = Path(__file__).resolve().parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))  # so task graders can import local helpers

try:
    from hud import Environment
    from hud.tools.coding import BashTool, ClaudeBashSession, EditTool
    from hud.tools.coding.utils import get_demote_preexec_fn
    from hud.tools.types import ContentResult, EvaluationResult, ToolError

    HUD_AVAILABLE = True
except (ImportError, ModuleNotFoundError):  # pragma: no cover - lets env.py import bare
    HUD_AVAILABLE = False

    class ToolError(RuntimeError):
        pass

    class ContentResult:  # type: ignore[no-redef]
        def __init__(self, output: str) -> None:
            self.output = output

        def to_content_blocks(self) -> list[dict[str, str]]:
            return [{"type": "text", "text": self.output}]

    class Environment:  # type: ignore[no-redef]
        def __init__(self, name: str) -> None:
            self.name = name

        def scenario(self, _name: str):
            def decorator(func):
                return func

            return decorator

        def tool(self):
            def decorator(func):
                return func

            return decorator

    BashTool = None  # type: ignore[assignment]
    ClaudeBashSession = object  # type: ignore[assignment]
    EditTool = object  # type: ignore[assignment]

    def get_demote_preexec_fn():  # type: ignore[no-redef]
        return None


WORKSPACE_DIR = Path(
    os.environ.get("WORKSPACE_DIR", "/workspace/target" if Path("/workspace").exists() else "/tmp/gdpval_workspace")
).resolve()
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
WORKSPACE_BASH_STREAM_LIMIT = 32 * 1024 * 1024

# Stripped from the solver shell so the agent cannot reach the judge or any key.
SOLVER_ENV_DROP_NAMES = {
    "HUD_API_KEY", "HUD_API_URL", "HUD_GATEWAY_URL",
    "GDPVAL_JUDGE_API_KEY", "GDPVAL_JUDGE_BASE_URL",
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
}
SOLVER_ENV_SECRET_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
# Blocked in solver shell commands to keep the evaluation offline.
EGRESS_PATTERNS = (
    r"\b(?:curl|wget|ssh|scp|sftp|ftp|nc|ncat|telnet|rsync)\b",
    r"\b(?:pip|pip3)\s+install\b",
    r"\bpython(?:3(?:\.\d+)?)?\s+-m\s+pip\s+install\b",
    r"\buv\s+(?:pip\s+)?(?:add|install|sync)\b",
    r"\bgit\s+(?:clone|fetch|pull|ls-remote|submodule\s+update)\b",
    r"\b(?:http|https|ftp|ssh)://",
    r"/dev/tcp/",
)


def _load_env_name() -> str:
    override = os.environ.get("GDPVAL_HUD_ENV", "").strip()
    if override:
        return override
    config_path = APP_ROOT / "config.toml"
    if config_path.is_file():
        with config_path.open("rb") as handle:
            hud = tomllib.load(handle).get("hud", {})
        name = hud.get("production_environment") or hud.get("environment")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return "gdpval-template"


ENV_NAME = _load_env_name()
env = Environment(name=ENV_NAME)


def _reject_solver_egress(command: str) -> None:
    lowered = command.lower()
    hits = [pat for pat in EGRESS_PATTERNS if re.search(pat, lowered)]
    if hits:
        raise ToolError(
            f"Network/egress is blocked in this offline evaluation (matched: {', '.join(hits)}). "
            "Work from the staged workspace artifacts."
        )


def _solver_subprocess_env() -> dict[str, str]:
    clean = dict(os.environ)
    for name in list(clean):
        if name in SOLVER_ENV_DROP_NAMES or any(marker in name for marker in SOLVER_ENV_SECRET_MARKERS):
            clean.pop(name, None)
    clean.update(
        {
            "HOME": "/home/solver" if Path("/home/solver").exists() else str(WORKSPACE_DIR),
            "USER": "solver",
            "LOGNAME": "solver",
            "XDG_CACHE_HOME": str(WORKSPACE_DIR / ".cache"),
            "TMPDIR": "/tmp",
        }
    )
    return clean


def _chown_solver_workspace() -> None:
    if os.getuid() != 0:
        return
    try:
        subprocess.run(["chown", "-R", "1000:1000", str(WORKSPACE_DIR)], check=True, capture_output=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:  # pragma: no cover
        print(f"[gdpval-env] warning: chown failed: {exc}", file=sys.stderr)


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
                    if not path.is_file():  # skip sockets, fifos, broken symlinks
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


def _resolve_deliverable(expected: Path) -> tuple[Path | None, dict[str, Any]]:
    """Resolve the agent's deliverable within the workspace, tolerating small naming
    slips, without forgiving genuinely missing work. Grading is scoped to the
    workspace only; files in scratch dirs are surfaced as diagnostics, never graded."""
    if expected.is_file():
        return expected, {}

    expected_name = expected.name.lower()
    expected_stem = expected.stem.lower()
    expected_suffix = expected.suffix.lower()
    files = _solver_files(WORKSPACE_DIR)
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
        "workspace_files": [_display(path) for path in files[:80]],
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
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(".gitkeep"))


def _load_grader(task_slug: str, grader_source: str):
    """Load the grader from a plaintext task arg (sync-only authoring) or, if none
    is supplied, from the image file tasks/<slug>/grader.py."""
    if grader_source.strip():
        module = types.ModuleType(f"gdpval_grader_arg_{abs(hash(task_slug))}")
        module.__dict__["__file__"] = str(APP_ROOT / "tasks" / task_slug / "grader.py")
        exec(compile(grader_source, "<grader_source>", "exec"), module.__dict__)  # noqa: S102 - task-author code
        return module
    grader_path = APP_ROOT / "tasks" / task_slug / "grader.py"
    spec = importlib.util.spec_from_file_location(f"gdpval_grader_{abs(hash(task_slug))}", grader_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load grader at {grader_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _grade(task_slug: str, deliverable: Path, grader_source: str, rubric_arg: Any) -> dict[str, Any]:
    grader = _load_grader(task_slug, grader_source)
    if isinstance(rubric_arg, dict) and rubric_arg:
        rubric = rubric_arg
    else:
        return _zero("missing_rubric_arg")
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


async def _run(task_slug: str, prompt: str, deliverable_rel: str,
               grader_source: str, rubric_arg: Any) -> AsyncGenerator[Any, None]:
    if not task_slug:
        raise RuntimeError("task args must include task_slug")
    deliverable = _deliverable_path(deliverable_rel)
    deliverable.parent.mkdir(parents=True, exist_ok=True)
    _stage_bundle(task_slug)
    _chown_solver_workspace()

    _ = yield _workspace_preamble(deliverable_rel) + prompt

    resolved_deliverable, resolution_info = _resolve_deliverable(deliverable)
    if resolved_deliverable is None:
        yield _to_eval(_zero("missing_deliverable", **resolution_info))
        return
    try:
        result = await _grade(task_slug, resolved_deliverable, grader_source, rubric_arg)
        if resolution_info:
            result.setdefault("info", {}).update(resolution_info)
        yield _to_eval(result)
    except Exception as exc:  # pragma: no cover - surfaces author errors
        yield _to_eval(_zero("grader_error", reason=repr(exc)[:500]))


# ---------------------------------------------------------------------------
# Solver tools — workspace-scoped bash + editor, offline, secrets stripped
# ---------------------------------------------------------------------------
if HUD_AVAILABLE:

    class _WorkspaceBashSession(ClaudeBashSession):  # type: ignore[misc, valid-type]
        async def start(self) -> None:
            if self._started:
                await asyncio.sleep(0)
                return
            self._process = await asyncio.create_subprocess_shell(
                self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(WORKSPACE_DIR),
                env=_solver_subprocess_env(),
                preexec_fn=get_demote_preexec_fn(),
                limit=WORKSPACE_BASH_STREAM_LIMIT,
            )
            self._started = True
            self._timed_out = False

        async def run(self, command: str) -> ContentResult:
            _reject_solver_egress(command)
            return await super().run(command)

    class _GuardedBashTool(BashTool):  # type: ignore[misc, valid-type]
        def __init__(self, timeout: float = ClaudeBashSession.DEFAULT_TIMEOUT) -> None:
            super().__init__(session=_WorkspaceBashSession(timeout=timeout), timeout=timeout)

        async def __call__(self, command: str | None = None, restart: bool = False):
            if restart:
                if self.session:
                    try:
                        self.session.stop()
                    except ToolError:
                        pass
                self.session = _WorkspaceBashSession(timeout=self._timeout)
                await self.session.start()
                return ContentResult(output="Bash session restarted.").to_content_blocks()
            if self.session is None or not isinstance(self.session, _WorkspaceBashSession):
                if self.session:
                    try:
                        self.session.stop()
                    except ToolError:
                        pass
                self.session = _WorkspaceBashSession(timeout=self._timeout)
            if command:
                _reject_solver_egress(command)
            return await super().__call__(command=command, restart=restart)

    class WorkspaceEditTool(EditTool):  # type: ignore[misc, valid-type]
        def _normalize(self, path: Path) -> Path:
            candidate = path if path.is_absolute() else WORKSPACE_DIR / path
            resolved = candidate.resolve()
            root = WORKSPACE_DIR.resolve()
            if resolved != root and root not in resolved.parents:
                raise ToolError(f"edit access denied outside workspace: {path}")
            return resolved

        def validate_path(self, command: str, path: Path) -> None:
            super().validate_path(command, self._normalize(path))

        async def __call__(self, *, command: EditCommand, path: str, file_text: str | None = None,
                           view_range: list[int] | None = None, old_str: str | None = None,
                           new_str: str | None = None, insert_line: int | None = None):
            return await super().__call__(
                command=command, path=str(self._normalize(Path(path))), file_text=file_text,
                view_range=view_range, old_str=old_str, new_str=new_str, insert_line=insert_line,
            )

    _GuardedBashTool().register(env)
    WorkspaceEditTool().register(env)


@env.tool()
async def submit():
    """Optional explicit completion signal."""
    return "submitted"


@env.scenario("gdpval_task")
async def gdpval_task(
    prompt: str = "Read the staged reference_files and produce the requested deliverable.",
    task_slug: str = "",
    deliverable: str = "deliverable/report.md",
    grader_source: str = "",
    rubric: dict[str, Any] | None = None,
) -> AsyncGenerator[Any, None]:
    # grader_source + rubric may travel as plaintext task args (sync-only authoring);
    # if omitted, the image copies under tasks/<slug>/ are used.
    async for item in _run(task_slug, prompt, deliverable, grader_source, rubric):
        yield item
