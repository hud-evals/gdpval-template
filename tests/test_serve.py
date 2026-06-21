"""Serve tests: the env stands up and grades end to end with no agent.

LocalRuntime by default; pass --image to run against a built image.
"""

import os

import pytest
from hud import Run, connect

from tasks import tasks as ALL_TASKS

pytestmark = pytest.mark.asyncio(loop_scope="session")

BY_SLUG = {t.slug: t for t in ALL_TASKS}


@pytest.mark.parametrize("slug", ["acct-afc-audit-sampling", "medsec-pathology-forms"])
async def test_serves_and_grades_missing_deliverable(runtime, slug):
    task = BY_SLUG[slug]
    async with runtime(task) as addr, connect(addr) as client:
        async with Run(client, task.id, task.args) as run:
            pass  # no agent writes a deliverable
    assert run.reward == 0.0
    info = (run.info or {}) if hasattr(run, "info") else {}
    # When the grader info is surfaced, it should say the deliverable was missing.
    if info.get("status"):
        assert info["status"] == "missing_deliverable"


async def test_grader_loads_in_served_env(runtime, tmp_path, monkeypatch):
    """Integration smoke: with a deliverable present, a served grade runs end to end
    and returns a non-error reward (the path a real rollout hits). The deterministic
    guard for the sibling-import bug is in test_grading.py."""
    from openpyxl import Workbook

    # Force the offline (deterministic-only) path so the test never calls the gateway.
    for key in list(os.environ):
        if "API_KEY" in key or key.startswith("HUD_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))

    task = BY_SLUG["acct-afc-audit-sampling"]
    deliv = tmp_path / "deliverable" / "Sample.xlsx"
    deliv.parent.mkdir(parents=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Sample"
    ws.append(["No"])
    ws.append([1])
    wb.save(str(deliv))

    async with runtime(task) as addr, connect(addr) as client:
        async with Run(client, task.id, task.args) as run:
            pass
    info = (run.info or {}) if hasattr(run, "info") else {}
    assert info.get("status") != "grader_error", f"grader failed to load: {info.get('reason')}"
    assert isinstance(run.reward, (int, float))
