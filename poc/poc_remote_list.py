"""POC payoff — list a real remote Takeout ZIP via range reads only.

Once poc_range_probe confirms the URL honors ranges, this lists the archive's
entries (name + size + album/folder path) by reading only the central directory
at the tail — no full download. Run it against your real Takeout URL to see the
true filenames/sizes and confirm the same-name/different-size duplicates exist.

Usage:
    uv run python poc/poc_remote_list.py "<URL>" [--header "Cookie: ..."] [--limit 40]
"""

from __future__ import annotations

import argparse
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gpdedup.http_range import HttpRangeReader, RangeNotSupported  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("url")
    ap.add_argument("--header", action="append", default=[])
    ap.add_argument("--limit", type=int, default=40, help="max entries to print")
    args = ap.parse_args()

    headers = {}
    for h in args.header:
        name, _, value = h.partition(":")
        headers[name.strip()] = value.strip()

    reader = HttpRangeReader(args.url, headers=headers)
    try:
        total = reader.size
        with zipfile.ZipFile(reader) as zf:
            infos = zf.infolist()
            list_bytes = reader.bytes_downloaded
            print(f"\nArchive size: {total:,} bytes  |  {len(infos)} entries")
            print(f"Listing cost: {list_bytes:,} bytes "
                  f"({list_bytes / total:.4%}) in {reader.request_count} requests\n")
            files = [i for i in infos if not i.is_dir()]
            for info in files[: args.limit]:
                print(f"{info.file_size:>12,}  {info.filename}")
            if len(files) > args.limit:
                print(f"... (+{len(files) - args.limit} more)")
    except RangeNotSupported as exc:
        print(f"\nRange not supported: {exc}")
        print("Use poc_range_probe first, or fall back to a Drive/Dropbox copy.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
