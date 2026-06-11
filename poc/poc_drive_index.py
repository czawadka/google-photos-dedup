"""Range-read Takeout zip parts straight from Google Drive and find duplicates.

For each Takeout part in Drive, this reads only the ZIP central directory (tail)
via the Range-capable Drive media endpoint — no full download — then unions all
entries and reports same-name / different-size duplicate candidates across parts.

This both (a) validates Part B (Drive honors Range -> 206) and (b) produces the
first real dedup result. Start with --max-parts 1 to confirm one part, then 0
for all.

Usage:
    export DRIVE_TOKEN="ya29...."
    uv run python poc/poc_drive_index.py --max-parts 1
    uv run python poc/poc_drive_index.py --max-parts 0
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
from gpdedup.grouping import group_candidates, is_media_file  # noqa: E402
from gpdedup.http_range import HttpRangeReader, RangeNotSupported  # noqa: E402
from gpdedup.report import search_url, write_html  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--token", default=None, help="OAuth access token (or set DRIVE_TOKEN)")
    ap.add_argument("--query", default=TAKEOUT_QUERY)
    ap.add_argument("--max-parts", type=int, default=1,
                    help="number of parts to read (0 = all)")
    ap.add_argument("--report", default="poc/duplicates.html",
                    help="path to write the clickable HTML worklist")
    ap.add_argument("--cache", default=CACHE_DEFAULT, help="SQLite cache path")
    ap.add_argument("--no-cache", action="store_true", help="don't read or write the cache")
    ap.add_argument("--refresh", action="store_true",
                    help="ignore cached entries and re-read parts from Drive")
    ap.add_argument("--offline", action="store_true",
                    help="rebuild from cache only (no token/network)")
    ap.add_argument("--explain", default=None,
                    help="print the per-copy breakdown for one filename (debug)")
    args = ap.parse_args()

    conn = None if args.no_cache else open_cache(args.cache)

    if args.offline:
        if conn is None:
            print("--offline needs the cache (don't combine with --no-cache).")
            return 1
        headers = {}
        parts = get_parts(conn)
    else:
        token = resolve_token(args.token)
        headers = auth_header(token)
        parts = [f for f in list_files(token, args.query)
                 if f.get("name", "").lower().endswith(".zip")]
    parts = sorted(parts, key=lambda x: x.get("name", ""))
    if not parts:
        print("No .zip parts found (offline cache empty?)." if args.offline
              else "No .zip parts matched the query.")
        return 1
    if args.max_parts > 0:
        parts = parts[: args.max_parts]

    entries: list[tuple[str, int]] = []
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
                print(f"  {name}: RANGE NOT SUPPORTED — {exc}")
                return 2
            if conn is not None:
                put_entries(conn, fid, name, size, mtime, part_entries)
            pct = reader.bytes_downloaded / size if size else 0
            note = f"read {reader.bytes_downloaded:,} bytes ({pct:.3%}) [drive]"
        else:
            note = "[cache]"

        media = [(n, s) for n, s in part_entries if is_media_file(n)]
        entries.extend(media)
        print(f"  {name}: {len(media):>5} media (of {len(part_entries)} entries) {note}")

    if args.explain:
        from gpdedup.grouping import is_album_path, normalize_base_name, summarize_group
        key = os.path.splitext(args.explain)[0].lower()
        matched = [(p, s) for p, s in entries
                   if os.path.splitext(normalize_base_name(p))[0].lower() == key]
        print(f"\n=== explain {args.explain!r} (indexed {len(parts)} part(s)) ===")
        if not matched:
            print("  no media entries with that name in the indexed parts "
                  "(try --max-parts 0 to read them all).")
            return 0
        for p, s in sorted(matched):
            print(f"  [{'ALBUM' if is_album_path(p) else 'year '}] {s:>12,}  {p}")
        print("  clusters by size (smallest = keeper):")
        for c in summarize_group(matched):
            print(f"    {'KEEP' if c['keeper'] else 'del '} {c['size']:>12,}  albums={c['albums']}")
        return 0

    candidates = group_candidates(entries)
    print(f"\nTotal entries: {len(entries):,}")
    print(f"Same-name / different-size duplicate candidates: {len(candidates)}\n")
    for name, items in sorted(candidates.items())[:25]:
        sizes = ", ".join(f"{s:,}" for _, s in sorted(items, key=lambda x: x[1]))
        print(f"  {name}: {len(items)} copies, sizes [{sizes}]")
        print(f"      {search_url(name)}")
    if len(candidates) > 25:
        print(f"  ... (+{len(candidates) - 25} more — see the HTML report)")

    if candidates:
        stats = write_html(candidates, args.report)
        print(f"\nWorklist written: {args.report}")
        print(f"  {stats['groups']} groups · {stats['reclaim']:,} bytes reclaimable · "
              f"{stats['album_actions']} album(s) need additions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
