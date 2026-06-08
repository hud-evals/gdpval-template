"""Reference files for medsec-pathology-forms.

The reference bundle is the REAL GDPval material, committed under reference_files/:
  reference_files/July 2025 - Bulk Form Needed.xlsx  (gdpval task a0552909-…, 30 patients / 3 labs)
  reference_files/REACH LOGO.pdf

To (re)fetch, use the repo-root downloader:
  uv run python download_reference_files.py --task medsec-pathology-forms

This script only writes provenance and verifies the real files are present.
"""

from __future__ import annotations

import json
from pathlib import Path

REFERENCE_FILES = Path(__file__).parent / "reference_files"
REAL_FILES = ["July 2025 - Bulk Form Needed.xlsx", "REACH LOGO.pdf"]


def main() -> int:
    REFERENCE_FILES.mkdir(parents=True, exist_ok=True)
    present = {f: (REFERENCE_FILES / f).is_file() for f in REAL_FILES}
    (REFERENCE_FILES / "provenance.json").write_text(json.dumps({
        "gdpval_task_id": "a0552909-bc66-4a3a-8970-ee0d17b49718",
        "source_dataset": "openai/gdpval (gold subset)",
        "artifacts": [
            {"path": "July 2025 - Bulk Form Needed.xlsx", "type": "xlsx",
             "provenance": "authentic GDPval reference file",
             "source_url": "https://huggingface.co/datasets/openai/gdpval/resolve/main/"
                           "reference_files/770ea5e60952d111e5403a1ea116646b/July%202025%20-%20Bulk%20Form%20Needed.xlsx"},
            {"path": "REACH LOGO.pdf", "type": "pdf",
             "provenance": "authentic GDPval reference file",
             "source_url": "https://huggingface.co/datasets/openai/gdpval/resolve/main/"
                           "reference_files/18778653fb8f70431e7237e613050563/REACH%20LOGO.pdf"},
        ],
        "present": present,
    }, indent=2), encoding="utf-8")
    print(f"provenance written; present={present}")
    return 0 if all(present.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
