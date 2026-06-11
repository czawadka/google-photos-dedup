"""Probe: does the ZIP entry timestamp match the sidecar photoTakenTime?

For a sample of duplicate-candidate groups, read for EACH copy both:
  - the ZIP central-directory timestamp (ZipInfo.date_time) — free in the read
    we already do; and
  - the sidecar `photoTakenTime` — the authoritative capture time.
and print them side by side. If the zip timestamp tracks photoTakenTime, we can
filter false-positive duplicates (same name, different photo, different date)
for free; otherwise we'd need the sidecar.

Usage:
    export DRIVE_TOKEN="ya29...."
    uv run python poc/poc_date_probe.py                 # sample 8 groups from cache
    uv run python poc/poc_date_probe.py IMG_0001.JPG ... # specific filenames
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gpdedup.cache import open_cache  # noqa: E402
from gpdedup.drive import auth_header, media_url, resolve_token  # noqa: E402
from gpdedup.grouping import _COLLISION, group_candidates, is_media_file  # noqa: E402
from gpdedup.http_range import HttpRangeReader  # noqa: E402

SAMPLE = 8


def split_collision(fname: str) -> tuple[str, str]:
    root, ext = os.path.splitext(fname)
    m = _COLLISION.match(root)
    return (m.group("stem") + ext, f"({m.group('n')})") if m else (fname, "")


def candidate_sidecars(media_path: str) -> list[str]:
    folder = media_path.rsplit("/", 1)[0] + "/" if "/" in media_path else ""
    fname = media_path.rsplit("/", 1)[-1]
    base, dupe = split_collision(fname)
    metas = [".supplemental-metadata", ".supplemental-met", ".suppl", ""]
    out = []
    for meta in metas:
        if dupe:
            out += [f"{folder}{base}{meta}{dupe}.json", f"{folder}{fname}{meta}.json"]
        else:
            out.append(f"{folder}{base}{meta}.json")
    return out


def taken_time(raw: bytes):
    try:
        ts = json.loads(raw)["photoTakenTime"]["timestamp"]
        return dt.datetime.utcfromtimestamp(int(ts))
    except (ValueError, KeyError, TypeError):
        return None


def main() -> int:
    conn = open_cache("poc/.cache.sqlite")
    rows = conn.execute("SELECT name, size, file_id FROM entries").fetchall()
    name_to_part = {n: fid for n, _, fid in rows}
    all_names_by_part: dict[str, set] = {}
    for n, _, fid in rows:
        all_names_by_part.setdefault(fid, set()).add(n)

    media = [(n, s) for n, s, _ in rows if is_media_file(n)]
    cands = group_candidates(media)

    wanted = sys.argv[1:]
    if wanted:
        stems = {os.path.splitext(w)[0] for w in wanted}
        names = [n for n in cands
                 if n in wanted or os.path.splitext(n)[0] in stems]
    else:
        names = sorted(cands)[:SAMPLE]
    if not names:
        print("No matching candidate groups. Pass exact normalized filenames or none.")
        return 1

    # collect the copies we need to read, grouped by part
    need: dict[str, list[str]] = {}
    for name in names:
        for path, _ in cands[name]:
            need.setdefault(name_to_part[path], []).append(path)

    part_name = {r[0]: r[1] for r in conn.execute("SELECT file_id, name FROM parts")}
    headers = auth_header(resolve_token(None))
    sidecar_raw: dict[str, bytes] = {}
    matched: dict[str, str] = {}
    json_sibs: dict[str, list] = {}
    for fid, paths in need.items():
        reader = HttpRangeReader(media_url(fid), headers=headers)
        with zipfile.ZipFile(reader) as zf:
            names_in_part = all_names_by_part[fid]
            for p in paths:
                sc = next((c for c in candidate_sidecars(p) if c in names_in_part), None)
                if sc:
                    matched[p] = sc
                    try:
                        sidecar_raw[p] = zf.read(sc)
                    except KeyError:
                        pass
                else:
                    folder = p.rsplit("/", 1)[0] + "/" if "/" in p else ""
                    stem = os.path.splitext(split_collision(p.rsplit("/", 1)[-1])[0])[0]
                    json_sibs[p] = sorted(
                        n for n in names_in_part
                        if n.startswith(folder) and n.endswith(".json")
                        and os.path.basename(n).startswith(stem))[:4]

    print("\nParts (zip files) read for this sample:")
    for fid in need:
        print(f"  {part_name.get(fid, '?')}  ({len(need[fid])} copies)")

    TOL = dt.timedelta(hours=24)
    for name in names:
        print(f"\n{name}")
        takens = []
        for path, size in sorted(cands[name], key=lambda x: x[1]):
            pn = part_name.get(name_to_part[path], "?")
            folder = path.rsplit("/", 1)[0].rsplit("/", 1)[-1] if "/" in path else ""
            tk = taken_time(sidecar_raw[path]) if path in sidecar_raw else None
            if tk:
                takens.append(tk)
            ts = tk.strftime("%Y-%m-%d %H:%M") if tk else "NO SIDECAR"
            tag = "keep" if size == min(s for _, s in cands[name]) else "del "
            print(f"  {tag} {size:>12,}  {pn:<36} {folder:<22.22} {ts}")
            if path not in matched:
                sibs = json_sibs.get(path, [])
                if sibs:
                    for js in sibs:
                        print(f"        .json in folder (matcher missed?): {os.path.basename(js)}")
                else:
                    print("        (no matching .json in this folder)")
        if len(takens) >= 2:
            spread = max(takens) - min(takens)
            v = "LEGIT" if spread <= TOL else "FALSE"
            print(f"  => sidecar verdict={v}  Δ={spread}")
        else:
            print(f"  => sidecar verdict=?  (only {len(takens)} sidecar date(s) found)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
