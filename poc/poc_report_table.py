"""Deprecated shim — the report pipeline now lives in gpdedup.cli (`uv run gpdedup`).

Kept so existing commands (`uv run python poc/poc_report_table.py ...`) keep working.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gpdedup.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
