"""Download authentic GDPval reference files for a task.

Reads each task's source `gdpval_task_id`, looks the task up in the public
openai/gdpval dataset, and downloads its real reference files (the binary
attachments) straight into `tasks/<slug>/reference_files/`. Offline-eval rule applies:
the files are baked into the image at deploy, never fetched at evaluation time.

Usage:
  uv run python download_reference_files.py                       # all tasks
  uv run python download_reference_files.py --task acct-afc-audit-sampling
  uv run python download_reference_files.py --list                # show task_ids + file counts

Network is required (this runs at authoring/build time, not during evaluation).
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
DATASET = "openai/gdpval"
ROWS_API = "https://datasets-server.huggingface.co/rows"


def _task_ids() -> dict[str, str]:
    """Map slug -> gdpval_task_id by reading each task.py."""
    ids: dict[str, str] = {}
    for task_py in (ROOT / "tasks").glob("*/task.py"):
        slug = task_py.parent.name
        for line in task_py.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("GDPVAL_TASK_ID"):
                ids[slug] = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    return ids


def _fetch_rows() -> dict[str, dict]:
    """Return {task_id: row} for the whole gold subset."""
    out: dict[str, dict] = {}
    for offset in range(0, 220, 100):
        url = f"{ROWS_API}?dataset={urllib.parse.quote(DATASET)}&config=default&split=train&offset={offset}&length=100"
        with urllib.request.urlopen(url, timeout=90) as resp:
            for r in json.load(resp)["rows"]:
                row = r["row"]
                out[row.get("task_id")] = row
    return out


def _download(url: str, dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "gdpval-template/1.0"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = resp.read()
    dest.write_bytes(data)
    return len(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", help="only this slug")
    parser.add_argument("--list", action="store_true", help="list task_ids + file counts and exit")
    args = parser.parse_args()

    slug_to_id = _task_ids()
    rows = _fetch_rows()

    if args.list:
        for slug, tid in sorted(slug_to_id.items()):
            files = rows.get(tid, {}).get("reference_file_urls", []) or []
            print(f"{slug}  {tid}  files={len(files)}")
        return 0

    targets = {args.task: slug_to_id[args.task]} if args.task else slug_to_id
    total = 0
    for slug, tid in targets.items():
        row = rows.get(tid)
        if not row:
            print(f"[{slug}] task_id {tid} not in gold subset — skipping")
            continue
        urls = row.get("reference_file_urls", []) or []
        names = [Path(p).name for p in (row.get("reference_files", []) or [])]
        if not urls:
            print(f"[{slug}] no reference files in GDPval — skipping")
            continue
        reference_dir = ROOT / "tasks" / slug / "reference_files"
        for url, name in zip(urls, names):
            size = _download(url, reference_dir / name)
            total += 1
            print(f"[{slug}] downloaded {name} ({size} bytes)")
    print(f"done; {total} file(s) downloaded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
