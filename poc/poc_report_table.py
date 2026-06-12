"""Generate the duplicate worklist table: filename · confirmed pair(s) · search link.

Range-reads each Takeout part's central directory (kilobytes, no pixel/sidecar
downloads) to find same-name / different-size candidate groups, then CONFIRMS each
by capture date: it range-reads every candidate copy's EXIF head (~64 KB, cached)
and keeps only groups with a real same-instant duplicate pair — dropping false
positives where a generic name (001.JPG, scanner counters) collides across
different photos taken months apart.

Emits an HTML table with one row per confirmed group: the filename, the duplicate
pair(s) (each pair's capture date + sizes, smallest tagged 'keep'), and a Google
Photos search link (encoded /search/<token> form so the literal filename —
underscores/UUIDs — survives Google's tokenizer).

The search link opens every copy of that filename; you decide which to keep from
the live "backed up / not consuming storage" status in the Photos UI (a signal not
present in the Takeout metadata). The date + sizes tell multiple pairs apart.

Usage:
    export DRIVE_TOKEN="ya29...."
    uv run python poc/poc_report_table.py --max-parts 0
    uv run python poc/poc_report_table.py --offline      # rebuild from cache, no token
"""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gpdedup.cache import (  # noqa: E402
    DEFAULT_PATH as CACHE_DEFAULT, get_entries, get_parts, open_cache, put_entries,
)
from gpdedup.central_dir import read_part_entries  # noqa: E402
from gpdedup.drive import (  # noqa: E402
    TAKEOUT_QUERY, auth_header, list_files, resolve_token,
)
from gpdedup.dating import capture_dates, real_dup_pairs  # noqa: E402
from gpdedup.grouping import (  # noqa: E402
    group_candidates, is_media_file, is_truncated_name,
)
from gpdedup.http_range import RangeNotSupported  # noqa: E402
from gpdedup.report import token_search_url, write_table_html  # noqa: E402
from gpdedup.sidecar import resolve_urls  # noqa: E402


def index_parts(args, conn):
    """Read every part's central directory. Returns (media, name_to_part):
    media = [(path, size)] and name_to_part = {path: file_id}."""
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
    name_to_part: dict[str, str] = {}
    print(f"Indexing {len(parts)} part(s):\n")

    def absorb(fid, name, part_entries, note):
        m = [(n, s) for n, s, _ in part_entries if is_media_file(n)]
        media.extend(m)
        for n, _ in m:
            name_to_part[n] = fid
        print(f"  {name}: {len(m):>5} media (of {len(part_entries)} entries) {note}")

    # Serve cached parts from SQLite (instant); read the rest concurrently.
    to_fetch = []
    for f in parts:
        fid, name = f["id"], f.get("name", "")
        size = int(f.get("size", 0) or 0)
        mtime = f.get("modifiedTime", "")
        cached = get_entries(conn, fid, size, mtime) \
            if conn is not None and not args.refresh else None
        if cached is not None:
            absorb(fid, name, cached, "[cache]")
        else:
            to_fetch.append((fid, name, size, mtime))

    if to_fetch:
        if args.offline:
            raise SystemExit(f"--offline but {len(to_fetch)} part(s) aren't cached; "
                             "run online once to index them.")
        with ThreadPoolExecutor(max_workers=args.max_workers) as ex:
            futs = {ex.submit(read_part_entries, fid, headers): (fid, name, size, mtime)
                    for fid, name, size, mtime in to_fetch}
            try:
                for fut in as_completed(futs):
                    fid, name, size, mtime = futs[fut]
                    part_entries, nbytes = fut.result()
                    if conn is not None:                 # persist on the main thread
                        put_entries(conn, fid, name, size, mtime, part_entries)
                    absorb(fid, name, part_entries, f"read {nbytes:,} bytes [drive]")
            except RangeNotSupported as exc:
                raise SystemExit(f"RANGE NOT SUPPORTED — {exc}")
    return media, name_to_part


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
    ap.add_argument("--max-workers", type=int, default=20,
                    help="max parallel EXIF-head fetches (adaptive, capped here)")
    ap.add_argument("--no-links", action="store_true",
                    help="skip per-copy sidecar deep-link resolution")
    args = ap.parse_args()

    conn = None if args.no_cache else open_cache(args.cache)
    media, name_to_part = index_parts(args, conn)
    candidates = group_candidates(media)
    print(f"\nName/size candidate groups: {len(candidates)}")

    # Drop Takeout-truncated names: a basename at the 51-char limit lost the tail
    # that tells distinct files apart, so different derived files (crops/rotations/
    # motion-portrait twins — not separate library items) merge into one false
    # same-name group. The date check can't catch them (renditions share one
    # capture instant), so exclude them before dating/report. See is_truncated_name.
    truncated = [name for name in candidates if is_truncated_name(name)]
    if truncated:
        for name in truncated:
            del candidates[name]
        print(f"Excluding {len(truncated)} truncated-name groups "
              f"(Takeout edit/rendition artifacts, not real library items)")

    # Confirm each candidate by capture date: range-read each copy's EXIF head
    # (cached), then keep only groups with a real same-instant dup pair. Drops
    # false positives where a generic name collides across different photos.
    need: dict[str, list[str]] = {}
    for name in candidates:
        for path, _ in candidates[name]:
            need.setdefault(name_to_part[path], []).append(path)
    headers = {} if args.offline else auth_header(resolve_token(args.token))

    phase = {"dating": False}

    def gather(done, total, nbytes):
        print(f"\r  reading central directories: {done}/{total} parts · "
              f"{nbytes / 1_000_000:.1f} MB", end="", flush=True)

    def show(done, total, nbytes, workers):
        if not phase["dating"]:                              # close the gather line once
            print()
            phase["dating"] = True
        print(f"\r  dating candidates: {done}/{total} copies · "
              f"{nbytes / 1_000_000:.1f} MB · {workers} workers", end="", flush=True)

    when, dstats = capture_dates(conn, need, headers, progress=show,
                                 max_workers=args.max_workers, on_gather=gather)
    if dstats["fetched"]:
        print()                                              # close the \r line
    print(f"Capture dates: {dstats['cached']} cached, {dstats['fetched']} range-read, "
          f"{dstats['uncached']} uncached · {dstats['bytes']:,} bytes")
    if dstats["uncached"]:
        print(f"  ⚠ {dstats['uncached']} copies have no cached date and weren't fetched "
              f"(offline) — their groups may be under-reported.")

    rows = []
    for name in sorted(candidates):
        pairs = real_dup_pairs(candidates[name], when)       # date-confirmed only
        if not pairs:
            continue
        term = os.path.splitext(name)[0]                     # search without the extension
        rows.append({
            "name": name,
            "search_url": token_search_url([term]),
            "pairs": pairs,
            "reclaim": sum(p["reclaim"] for p in pairs),
        })

    # Per-copy deep links: resolve each confirmed copy's sidecar `url` so a generic
    # name (001.JPG -> 100s of search hits) links straight to the exact copy. Only
    # confirmed copies are fetched (cache-first, parallel); offline/--no-links just
    # renders the sizes unlinked and falls back to the group search link.
    url_by_path: dict[str, str] = {}
    if not args.no_links:
        copy_paths = [p for r in rows for pair in r["pairs"] for p, _ in pair["copies"]]

        def show_links(done, total, workers):
            print(f"\r  sidecar links: {done}/{total} copies · {workers} workers",
                  end="", flush=True)

        url_by_path = resolve_urls(conn, copy_paths, headers or None,
                                   max_workers=args.max_workers, progress=show_links)
        resolved = sum(1 for p in copy_paths if p in url_by_path)
        if copy_paths and url_by_path:
            print()                                          # close the \r line
        print(f"Sidecar links: {resolved}/{len(copy_paths)} copies resolved")

    stats = write_table_html(rows, args.report, url_by_path)
    print(f"\nTable written: {args.report}")
    print(f"  {stats['rows']} confirmed groups (of {len(candidates)} candidates) · "
          f"{stats['reclaim']:,} bytes reclaimable (if smallest in each pair kept)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
