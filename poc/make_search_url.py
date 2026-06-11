"""Build a Google Photos OR-search deep link from arbitrary filename terms.

Handy for ad-hoc searches. Google Photos ORs quoted bare names but ANDs
extension terms, so pass base names without extension.
(Note: searching by internal item id does NOT work — filenames only.)

Usage:
    uv run python poc/make_search_url.py "IMG_6799" "IMG_6813" "IMG_6885"
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gpdedup.report import or_search_url  # noqa: E402


def main() -> int:
    terms = sys.argv[1:]
    if not terms:
        print(__doc__)
        return 1
    print(or_search_url(terms))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
