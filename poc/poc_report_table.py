"""Generate the duplicate worklist table: filename · sizes · search link.

Range-reads each Takeout part's central directory (kilobytes, no pixel/sidecar
downloads) to find same-name / different-size duplicate groups, and emits an HTML
table with one row per group: the filename, the copies' sizes (smallest tagged
'keep'), and a Google Photos search link (encoded /search/<token> form so the
literal filename — underscores/UUIDs — survives Google's tokenizer).

The search link opens BOTH copies; you decide which to keep from the live
"backed up / not consuming storage" status in the Photos UI (a signal not present
in the Takeout metadata).

Usage:
    export DRIVE_TOKEN="ya29...."
    uv run python poc/poc_report_table.py --max-parts 0
    uv run python poc/poc_report_table.py --offline      # rebuild from cache, no token
"""

from __future__ import annotations

import argparse
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gpdedup.cache import (  # noqa: E402
    DEFAULT_PATH as CACHE_DEFAULT, get_entries, get_parts, open_cache, put_entries,
)
from gpdedup.drive import (  # noqa: E402
    TAKEOUT_QUERY, auth_header, list_files, media_url, resolve_token,
)
from gpdedup.grouping import group_candidates, is_media_file, summarize_group  # noqa: E402
from gpdedup.http_range import HttpRangeReader, RangeNotSupported  # noqa: E402
from gpdedup.report import token_search_url, write_table_html  # noqa: E402


def index_parts(args, conn):
    """Read every part's central directory. Returns media = [(path, size)]."""
    if args.offline:
        if conn is None:
            raise SystemExit("--offline needs the cache (don't combine with --no-cache).")
        headers, parts = {}, get_parts(conn)
    else:
        token = resolve_token(args.token)
        headers = auth_header(token)
        parts = [f for f in list_files(token, args.query)
                 if f.get("name", "").lower().endswith(".zip")]
    parts = sorted(parts, key=lambda x: x.get("name", ""))
    if not parts:
        raise SystemExit("No .zip parts found.")
    if args.max_parts > 0:
        parts = parts[: args.max_parts]

    media: list[tuple[str, int]] = []
    print(f"Indexing {len(parts)} part(s):\n")
    for f in parts:
        fid, name = f["id"], f.get("name", "")
        size = int(f.get("size", 0) or 0)
        mtime = f.get("modifiedTime", "")

        part_entries = None
        if conn is not None and not args.refresh:
            part_entries = get_entries(conn, fid, size, mtime)
        if part_entries is None:
            reader = HttpRangeReader(media_url(fid), headers=headers)
            try:
                with zipfile.ZipFile(reader) as zf:
                    part_entries = [(i.filename, i.file_size)
                                    for i in zf.infolist() if not i.is_dir()]
            except RangeNotSupported as exc:
                raise SystemExit(f"  {name}: RANGE NOT SUPPORTED — {exc}")
            if conn is not None:
                put_entries(conn, fid, name, size, mtime, part_entries)
            note = f"read {reader.bytes_downloaded:,} bytes [drive]"
        else:
            note = "[cache]"

        m = [(n, s) for n, s in part_entries if is_media_file(n)]
        media.extend(m)
        print(f"  {name}: {len(m):>5} media (of {len(part_entries)} entries) {note}")
    return media


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--token", default=None, help="OAuth access token (or set DRIVE_TOKEN)")
    ap.add_argument("--query", default=TAKEOUT_QUERY)
    ap.add_argument("--max-parts", type=int, default=0, help="parts to read (0 = all)")
    ap.add_argument("--report", default="poc/delete_table.html")
    ap.add_argument("--cache", default=CACHE_DEFAULT)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--refresh", action="store_true", help="re-read central dirs from Drive")
    ap.add_argument("--offline", action="store_true", help="cache only; no token/network")
    args = ap.parse_args()

    conn = None if args.no_cache else open_cache(args.cache)
    media = index_parts(args, conn)
    candidates = group_candidates(media)
    print(f"\nDuplicate groups: {len(candidates)}")

    rows = []
    for name in sorted(candidates):
        clusters = summarize_group(candidates[name])         # distinct sizes, smallest first
        term = os.path.splitext(name)[0]                     # search without the extension
        rows.append({
            "name": name,
            "search_url": token_search_url([term]),
            "sizes": [c["size"] for c in clusters],          # ascending; [0] = smallest
            "reclaim": sum(c["size"] for c in clusters[1:]),
        })

    stats = write_table_html(rows, args.report)
    print(f"\nTable written: {args.report}")
    print(f"  {stats['rows']} groups · {stats['reclaim']:,} bytes reclaimable (if smallest kept)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
