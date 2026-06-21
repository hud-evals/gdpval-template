"""Task collection entrypoint for `hud eval` / `hud sync tasks`.

Collects the public ``tasks`` list; ``env`` is re-exported so the loader can find
the Environment when serving this source.
"""

from env import env, gdpval_task  # noqa: F401  (re-exported so the loader finds the env)

from tasks import task_ids, tasks

__all__ = ["env", "gdpval_task", "task_ids", "tasks"]
