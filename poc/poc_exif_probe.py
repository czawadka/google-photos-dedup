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

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gpdedup.cache import open_cache  # noqa: E402
from gpdedup.dating import capture_dates, real_dup_pairs  # noqa: E402
from gpdedup.drive import auth_header, resolve_token  # noqa: E402
from gpdedup.grouping import group_candidates, is_media_file  # noqa: E402

SAMPLE = 8


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

    when, stats = capture_dates(conn, need, auth_header(resolve_token(None)))

    for name in names:
        print(f"\n{name}")
        for path, size in sorted(cands[name], key=lambda x: x[1]):
            d = when.get(path)
            ds = d.strftime("%Y-%m-%d %H:%M:%S") if d else "(no exif)"
            print(f"  {size:>12,}  {ds}")

        pairs = real_dup_pairs(cands[name], when)
        if pairs:
            print(f"  => {len(pairs)} real dup pair(s) inside this group:")
            for p in pairs:
                print(f"       {p['when']:%Y-%m-%d %H:%M:%S}  "
                      f"sizes={p['sizes']}  keep={p['keep']:,}")
        else:
            print("  => no real dup (copies >12h apart — different photos "
                  "sharing the name)")

    copies = sum(len(v) for v in need.values())
    print(f"\n{copies} copies: {stats['cached']} from cache, {stats['fetched']} "
          f"range-read · {stats['bytes']:,} bytes "
          f"(~{stats['bytes'] // max(stats['fetched'], 1):,} B/fetched file). "
          f"No sidecars, no full images.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
