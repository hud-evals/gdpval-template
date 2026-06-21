"""In-process wiring smoke tests for the v6 environment (no Docker, no serve).

Confirms the template is registered and the task rows are well-formed, so
authoring mistakes surface fast without a build.
"""

from env import env
from tasks import tasks


def test_template_registered():
    assert "gdpval_task" in env.tasks
    assert env.tasks["gdpval_task"].manifest_entry()["id"] == "gdpval_task"


def test_env_identity():
    assert env.name == "gdpval-template"


def test_tasks_collected():
    """`hud eval` / `hud sync` collect the public ``tasks`` list."""
    assert len(tasks) == 2
    slugs = {t.slug for t in tasks}
    assert slugs == {"acct-afc-audit-sampling", "medsec-pathology-forms"}
    assert len(slugs) == len(tasks), "task slugs must be unique"

    for task in tasks:
        assert task.env == "gdpval-template"
        assert task.id == "gdpval_task"
        assert task.args.get("task_slug") == task.slug
        # rubric (answer key) and grader source travel only as task args
        assert isinstance(task.args.get("rubric"), dict) and task.args["rubric"]
        assert task.args.get("grader_source")
        assert task.columns and "occupation" in task.columns  # leaderboard facets
