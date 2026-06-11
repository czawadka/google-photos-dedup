"""Probe: date duplicate candidates from the media file's EXIF via range reads.

Instead of sidecars, range-read only the first ~64 KB of each candidate copy
(the JPEG APP1/EXIF segment) straight from the Takeout zip and parse
DateTimeOriginal. Proves we can get the authoritative capture date per FILE
without sidecars and without downloading whole images — then applies the
same-name + |Δ| <= 24h rule and reports total bytes pulled.

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

from gpdedup.cache import open_cache  # noqa: E402
from gpdedup.drive import auth_header, media_url, resolve_token  # noqa: E402
from gpdedup.exif import read_exif_datetime  # noqa: E402
from gpdedup.grouping import group_candidates, is_media_file  # noqa: E402
from gpdedup.http_range import HttpRangeReader  # noqa: E402

HEAD = 64 * 1024
SAMPLE = 8
TOL = dt.timedelta(hours=24)


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

    headers = auth_header(resolve_token(None))
    when: dict[str, dt.datetime] = {}
    total_bytes = 0
    for fid, paths in need.items():
        reader = HttpRangeReader(media_url(fid), headers=headers)
        with zipfile.ZipFile(reader) as zf:
            for p in paths:
                try:
                    with zf.open(p) as fp:
                        head = fp.read(HEAD)        # only the EXIF-bearing head
                    d = read_exif_datetime(head)
                    if d:
                        when[p] = d
                except (KeyError, zipfile.BadZipFile, OSError):
                    pass
        total_bytes += reader.bytes_downloaded

    for name in names:
        print(f"\n{name}")
        dates = []
        for path, size in sorted(cands[name], key=lambda x: x[1]):
            d = when.get(path)
            if d:
                dates.append(d)
            tag = "keep" if size == min(s for _, s in cands[name]) else "del "
            ds = d.strftime("%Y-%m-%d %H:%M:%S") if d else "(no exif)"
            print(f"  {tag} {size:>12,}  {ds}")
        if len(dates) >= 2:
            spread = max(dates) - min(dates)
            v = "LEGIT dup" if spread <= TOL else "FALSE (different photos)"
            print(f"  => {v}  Δ={spread}")
        else:
            print(f"  => ?  (only {len(dates)} exif date(s))")

    copies = sum(len(v) for v in need.values())
    print(f"\nRead {copies} file heads · {total_bytes:,} bytes total "
          f"(~{total_bytes // max(copies, 1):,} B/file). No sidecars, no full images.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
