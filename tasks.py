"""HUD task collection entrypoint.

This lets both forms work:
  hud sync tasks <taskset_name>
  hud sync tasks <taskset_name> tasks/
"""

from tasks import task_ids, tasks

__all__ = ["tasks", "task_ids"]
