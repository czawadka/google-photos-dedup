"""Generate a 3-column delete table: filename · search link · direct delete link.

Like poc_drive_index.py this range-reads each Takeout part's central directory to
find same-name / different-size duplicate groups (keeper = smallest). But for the
copies to DELETE (the larger ones) it goes one step further: it range-extracts
that copy's sidecar JSON and reads its `url` field — the
https://photos.google.com/photo/<id> deep link to that exact library item — so
the report can link straight to the copy to delete (no eyeballing two identical
search hits).

Sidecar `url`s are cached (SQLite) so reruns / --offline don't re-fetch them.

Usage:
    export DRIVE_TOKEN="ya29...."
    uv run python poc/poc_report_table.py --max-parts 0
    uv run python poc/poc_report_table.py --offline      # cached urls only
"""

from __future__ import annotations

import argparse
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gpdedup.cache import (  # noqa: E402
    DEFAULT_PATH as CACHE_DEFAULT, get_entries, get_parts, get_sidecar_url,
    open_cache, put_entries, put_sidecar_url,
)
from gpdedup.drive import (  # noqa: E402
    TAKEOUT_QUERY, auth_header, list_files, media_url, resolve_token,
)
from gpdedup.grouping import group_candidates, is_media_file, summarize_group  # noqa: E402
from gpdedup.http_range import HttpRangeReader, RangeNotSupported  # noqa: E402
from gpdedup.report import search_url, write_table_html  # noqa: E402
from gpdedup.sidecar import (  # noqa: E402
    build_sidecar_index, is_sidecar, match_sidecar, url_from_sidecar_bytes,
)


def index_parts(args, conn):
    """Read every part's central directory. Returns (media, part_names, part_by_id):
    media = [(path, size, part_id)], part_names = {part_id: set(all entry names)},
    part_by_id = {part_id: drive-meta dict}."""
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

    media: list[tuple[str, int, str]] = []
    part_names: dict[str, set] = {}
    part_by_id: dict[str, dict] = {}
    print(f"Indexing {len(parts)} part(s):\n")
    for f in parts:
        fid, name = f["id"], f.get("name", "")
        size = int(f.get("size", 0) or 0)
        mtime = f.get("modifiedTime", "")
        part_by_id[fid] = f

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

        part_names[fid] = {n for n, _ in part_entries}
        m = [(n, s, fid) for n, s in part_entries if is_media_file(n)]
        media.extend(m)
        print(f"  {name}: {len(m):>5} media (of {len(part_entries)} entries) {note}")
    return media, part_names, part_by_id


def fetch_sidecar_urls(needed, part_names, part_by_id, conn, headers, offline):
    """needed = {part_id: {media_path: sidecar_path}}. Returns {media_path: url|None}.
    Uses cached urls; otherwise range-reads sidecars from each part once."""
    urls: dict[str, str | None] = {}
    for fid, mapping in needed.items():
        # resolve from cache first
        to_read = {}
        for media_path, sidecar in mapping.items():
            cached = get_sidecar_url(conn, fid, sidecar) if conn is not None else None
            if cached is not None:
                urls[media_path] = cached or None
            else:
                to_read[media_path] = sidecar
        if not to_read:
            continue
        if offline:
            for media_path in to_read:
                urls[media_path] = None
            continue
        # one ZipFile per part; pull each needed sidecar's bytes
        reader = HttpRangeReader(media_url(fid), headers=headers)
        with zipfile.ZipFile(reader) as zf:
            for media_path, sidecar in to_read.items():
                try:
                    raw = zf.read(sidecar)
                    url = url_from_sidecar_bytes(raw)
                except KeyError:
                    url = None
                urls[media_path] = url
                if conn is not None:
                    put_sidecar_url(conn, fid, sidecar, url or "")
        print(f"  read {len(to_read)} sidecar(s) from {part_by_id[fid].get('name','')} "
              f"({reader.bytes_downloaded:,} bytes)")
    return urls


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
    ap.add_argument("--diagnose", type=int, default=0, metavar="N",
                    help="print N unmatched copies + the .json entries in their folder")
    args = ap.parse_args()

    conn = None if args.no_cache else open_cache(args.cache)
    headers = {} if args.offline else auth_header(resolve_token(args.token))

    media, part_names, part_by_id = index_parts(args, conn)
    path_to_part = {p: fid for p, _, fid in media}
    # One sidecar index per part (built once, reused for every lookup).
    part_index = {fid: build_sidecar_index(names) for fid, names in part_names.items()}
    candidates = group_candidates([(p, s) for p, s, _ in media])
    print(f"\nDuplicate groups: {len(candidates)}")

    needed: dict[str, dict] = {}  # part_id -> {media_path: sidecar_path}
    misses: list[str] = []

    def resolve(cluster) -> str | None:
        """Pick a media path for this library item and queue its sidecar fetch.
        The item can sit at several paths (year + album); any one's sidecar works."""
        for cand_path in sorted(cluster["paths"]):
            fid = path_to_part.get(cand_path)
            sc = match_sidecar(cand_path, part_index.get(fid, {})) if fid else None
            if sc:
                needed.setdefault(fid, {})[cand_path] = sc
                return cand_path
        misses.append(sorted(cluster["paths"])[0])
        return None

    # Resolve a sidecar (= unique id) for EVERY copy: keeper and each to-delete.
    rows: list[dict] = []
    for name in sorted(candidates):
        clusters = summarize_group(candidates[name])
        term = os.path.splitext(name)[0]             # search without the extension
        keep = clusters[0]
        keep_path = resolve(keep)
        for c in clusters[1:]:                        # everything but the smallest
            del_path = resolve(c)
            rows.append({"name": name, "search_url": search_url(term),
                         "keep_path": keep_path, "keep_size": keep["size"],
                         "delete_path": del_path, "delete_size": c["size"]})

    copies = sum(len(summarize_group(candidates[n])) for n in candidates)
    print(f"Distinct copies (ids to fetch): {copies} · matched: {copies - len(misses)} · "
          f"unmatched: {len(misses)}")
    if args.diagnose and misses:
        print(f"\n--- {min(args.diagnose, len(misses))} unmatched copies "
              f"(media path, then .json siblings in that folder) ---")
        for path in misses[: args.diagnose]:
            folder = path.replace("\\", "/").rsplit("/", 1)[0] + "/"
            fid = path_to_part.get(path)
            sibs = sorted(n for n in part_names.get(fid, set())
                          if is_sidecar(n) and n.startswith(folder))[:6]
            print(f"\n  MEDIA: {path}")
            for s in sibs:
                print(f"   json: {s}")
        print()
    print("resolving sidecar links...")
    urls = fetch_sidecar_urls(needed, part_names, part_by_id, conn, headers, args.offline)
    clashes = 0
    for r in rows:
        r["keep_url"] = urls.get(r["keep_path"]) if r["keep_path"] else None
        r["delete_url"] = urls.get(r["delete_path"]) if r["delete_path"] else None
        # Uniqueness assertion: the two copies MUST have different ids.
        if r["keep_url"] and r["delete_url"] and r["keep_url"] == r["delete_url"]:
            clashes += 1
            r["clash"] = True

    stats = write_table_html(rows, args.report)
    print(f"\nTable written: {args.report}")
    print(f"  {stats['rows']} rows · {stats['linked_delete']} delete-links · "
          f"{stats['linked_keep']} keep-links")
    if clashes:
        print(f"  ⚠ {clashes} group(s) had IDENTICAL keep/delete urls — those ids do NOT "
              f"distinguish the copies; treat their direct links with suspicion.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
