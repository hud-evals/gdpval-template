"""Reference files for acct-afc-audit-sampling.

The reference bundle is the REAL GDPval file, committed under reference_files/:
  reference_files/Population v2.xlsx  (gdpval task 83d10b06-…, 1,516 KRI rows)

To (re)fetch it, use the repo-root downloader:
  uv run python download_reference_files.py --task acct-afc-audit-sampling

This script only writes provenance and verifies the real file is present.
"""

from __future__ import annotations

import json
from pathlib import Path

REFERENCE_FILES = Path(__file__).parent / "reference_files"
REAL_FILE = "Population v2.xlsx"


def main() -> int:
    REFERENCE_FILES.mkdir(parents=True, exist_ok=True)
    present = (REFERENCE_FILES / REAL_FILE).is_file()
    (REFERENCE_FILES / "provenance.json").write_text(json.dumps({
        "gdpval_task_id": "83d10b06-26d1-4636-a32c-23f92c57f30b",
        "source_dataset": "openai/gdpval (gold subset)",
        "artifacts": [{
            "path": REAL_FILE,
            "type": "xlsx",
            "provenance": "authentic GDPval reference file",
            "source_url": "https://huggingface.co/datasets/openai/gdpval/resolve/main/"
                          "reference_files/cc781e4dc0985c8eb327a53ec03b5900/Population%20v2.xlsx",
            "present": present,
        }],
    }, indent=2), encoding="utf-8")
    print(f"provenance written; real file present={present}")
    return 0 if present else 1


if __name__ == "__main__":
    raise SystemExit(main())
