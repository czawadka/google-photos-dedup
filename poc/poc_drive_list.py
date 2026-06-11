"""List Google Drive Takeout archive parts (id, size, name) via the Drive API.

Get an OAuth access token with the drive.readonly scope:
  1. https://developers.google.com/oauthplayground
  2. In "Step 1", paste scope:  https://www.googleapis.com/auth/drive.readonly
  3. Authorize, then "Exchange authorization code for tokens" -> copy the access token.

Usage (keep the token out of shell history via env):
    export DRIVE_TOKEN="ya29...."
    uv run python poc/poc_drive_list.py
    # or:
    uv run python poc/poc_drive_list.py --token "ya29...." --query "name contains 'takeout'"
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gpdedup.drive import TAKEOUT_QUERY, list_files, media_url, resolve_token  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--token", default=None, help="OAuth access token (or set DRIVE_TOKEN)")
    ap.add_argument("--query", default=TAKEOUT_QUERY, help="Drive files.list query")
    args = ap.parse_args()
    token = resolve_token(args.token)

    files = list_files(token, args.query)
    if not files:
        print("No files matched. Adjust --query (the export may be in a 'Takeout' folder).")
        return 1

    total = 0
    print(f"{'size':>14}  {'id':<36}  name")
    print("-" * 90)
    for f in sorted(files, key=lambda x: x.get("name", "")):
        size = int(f.get("size", 0) or 0)
        total += size
        print(f"{size:>14,}  {f['id']:<36}  {f['name']}")
    print(f"\n{len(files)} files, {total:,} bytes total\n")

    first = sorted(files, key=lambda x: x.get("name", ""))[0]
    print("Next — confirm Range works on one part:")
    print(f'  uv run python poc/poc_range_probe.py "{media_url(first["id"])}" '
          f'-H "Authorization: Bearer $DRIVE_TOKEN"')
    print("Then index all parts:")
    print("  uv run python poc/poc_drive_index.py            # --max-parts 0 for all")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
