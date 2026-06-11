"""Probe: date duplicate candidates from the media file's EXIF via range reads.

Instead of sidecars, range-read only the first ~64 KB of each candidate copy
(the JPEG APP1/EXIF segment) straight from the Takeout zip and parse
DateTimeOriginal. Proves we can get the authoritative capture date per FILE
without sidecars and without downloading whole images — then clusters copies by
capture time (<=12h) to surface real dup pairs. Dates are cached so repeat runs
go offline; the summary reports cache hits vs. range-reads and bytes pulled.

Usage:
    export DRIVE_TOKEN="ya29...."
    uv run python poc/poc_exif_probe.py                 # 8 sampled groups
    uv run python poc/poc_exif_probe.py 001.JPG 002.JPG # specific names
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gpdedup.cache import get_exif_dates, open_cache, put_exif_dates  # noqa: E402
from gpdedup.drive import auth_header, media_url, resolve_token  # noqa: E402
from gpdedup.exif import read_exif_datetime  # noqa: E402
from gpdedup.grouping import group_candidates, is_media_file  # noqa: E402
from gpdedup.http_range import HttpRangeReader  # noqa: E402

HEAD = 64 * 1024
SAMPLE = 8
TOL = dt.timedelta(hours=12)


def cluster_by_time(timed, tol):
    """Group (datetime, size) copies into time-clusters: a new cluster starts
    whenever the gap to the previous copy exceeds `tol`. Real duplicates share
    the same capture instant, so they land in the same cluster; unrelated photos
    that merely collided on a generic name split into separate clusters."""
    clusters = []
    for d, size in sorted(timed):
        if clusters and d - clusters[-1][-1][0] <= tol:
            clusters[-1].append((d, size))
        else:
            clusters.append([(d, size)])
    return clusters


def main() -> int:
    conn = open_cache("poc/.cache.sqlite")
    rows = conn.execute("SELECT name, size, file_id FROM entries").fetchall()
    name_to_part = {n: fid for n, _, fid in rows}
    media = [(n, s) for n, s, _ in rows if is_media_file(n)]
    cands = group_candidates(media)

    wanted = sys.argv[1:]
    if wanted:
        stems = {os.path.splitext(w)[0] for w in wanted}
        names = [n for n in cands if n in wanted or os.path.splitext(n)[0] in stems]
    else:
        names = sorted(cands)[:SAMPLE]
    if not names:
        print("No matching candidate groups.")
        return 1

    need: dict[str, list[str]] = {}
    for name in names:
        for path, _ in cands[name]:
            need.setdefault(name_to_part[path], []).append(path)

    # Serve dates from cache; range-read only the copies we haven't probed yet.
    when: dict[str, dt.datetime] = {}
    fetch: dict[str, list[str]] = {}
    cached_hits = 0
    for fid, paths in need.items():
        have = get_exif_dates(conn, fid)
        for p in paths:
            if p in have:
                cached_hits += 1
                if have[p]:
                    when[p] = have[p]
            else:
                fetch.setdefault(fid, []).append(p)

    total_bytes = 0
    fetched = 0
    if fetch:
        headers = auth_header(resolve_token(None))
        for fid, paths in fetch.items():
            probed: list[tuple[str, dt.datetime | None]] = []
            reader = HttpRangeReader(media_url(fid), headers=headers)
            with zipfile.ZipFile(reader) as zf:
                for p in paths:
                    d = None
                    try:
                        with zf.open(p) as fp:
                            head = fp.read(HEAD)    # only the EXIF-bearing head
                        d = read_exif_datetime(head)
                    except (KeyError, zipfile.BadZipFile, OSError):
                        pass
                    probed.append((p, d))           # store None too (dateless)
                    if d:
                        when[p] = d
            put_exif_dates(conn, fid, probed)
            fetched += len(paths)
            total_bytes += reader.bytes_downloaded

    for name in names:
        print(f"\n{name}")
        timed = []
        for path, size in sorted(cands[name], key=lambda x: x[1]):
            d = when.get(path)
            if d:
                timed.append((d, size))
            ds = d.strftime("%Y-%m-%d %H:%M:%S") if d else "(no exif)"
            print(f"  {size:>12,}  {ds}")

        # Real duplicates are pairwise: copies sharing a capture instant (within
        # TOL) AND differing in size. Cluster by time, then test each cluster.
        clusters = cluster_by_time(timed, TOL)
        dup_clusters = [c for c in clusters if len({s for _, s in c}) > 1]
        if dup_clusters:
            print(f"  => {len(dup_clusters)} real dup pair(s) inside this group:")
            for c in dup_clusters:
                sizes = sorted(s for _, s in c)
                span = max(d for d, _ in c) - min(d for d, _ in c)
                keep = min(sizes)
                print(f"       {c[0][0]:%Y-%m-%d %H:%M:%S}  Δ={span}  "
                      f"sizes={sizes}  keep={keep:,}")
        else:
            print(f"  => no real dup (all {len(clusters)} copies "
                  f">{TOL} apart — different photos sharing the name)")

    copies = sum(len(v) for v in need.values())
    print(f"\n{copies} copies: {cached_hits} from cache, {fetched} range-read "
          f"· {total_bytes:,} bytes "
          f"(~{total_bytes // max(fetched, 1):,} B/fetched file). "
          f"No sidecars, no full images.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
