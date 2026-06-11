"""Capture-date dating + time-clustering to confirm real duplicates.

Same-name / different-size grouping alone over-reports: generic filenames
(`001.JPG`, scanner counters) collide across *different* photos. The fix is a
capture-date check — but it must be **pairwise**, not group-wide: a generic-name
group is a mix of several unrelated photos PLUS one or more real dup pairs hidden
inside, so a group-wide min/max spread would discard the real dups with the rest.

So we cluster the copies of one name by capture time: copies within `TOL` of each
other form a cluster, and a cluster holding >=2 copies of differing size is a real
duplicate (the same photo re-encoded — its EXIF DateTimeOriginal is preserved, so
the twins land at the *same instant*). Unrelated photos sharing the name fall into
separate, single-size clusters and are dropped.

Dates come from each file's EXIF head (first ~64 KB, where the JPEG APP1 segment
lives) range-read straight from the Takeout zip — KB per file, no sidecars, no
full images — and are cached so repeat runs go offline.
"""

from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed

from .cache import (
    get_entry_offsets, get_exif_dates, put_entry_offsets, put_exif_dates,
)
from .central_dir import read_part_entries
from .concurrency import AdaptiveLimiter
from .drive_fetch import (
    AuthError, RateLimited, TransientError, fetch_head, make_session,
)
from .exif import read_exif_datetime

TOL = dt.timedelta(hours=12)
MAX_TRIES = 6                  # per-file attempts before recording it dateless


def cluster_by_time(timed, tol=TOL):
    """Group items into time-clusters, starting a new cluster whenever the gap to
    the previous item exceeds `tol`. `timed` is an iterable of (datetime, payload);
    returns a list of clusters, each a list of (datetime, payload) sorted by time."""
    clusters: list[list] = []
    for d, payload in sorted(timed, key=lambda x: x[0]):
        if clusters and d - clusters[-1][-1][0] <= tol:
            clusters[-1].append((d, payload))
        else:
            clusters.append([(d, payload)])
    return clusters


def capture_dates(conn, need, headers=None, progress=None, max_workers=20,
                  on_gather=None):
    """Resolve capture dates for the given copies, cache-first and in parallel.

    `need` is {file_id: [paths]}. Returns (when, stats) where `when` maps path ->
    datetime (paths with no EXIF date are simply absent). Cached dates are served
    without network; the rest are fetched only when `headers` is provided
    (online), each over a pooled keep-alive session with adaptive concurrency
    (up to `max_workers`) and rate-limit backoff. Every result is persisted as it
    lands, so an interrupt loses nothing and a re-run resumes (the cache-first
    filter excludes already-stored paths).

    `on_gather(parts_done, parts_total, bytes)` is called after each part's
    central-directory read (the prelude that produces no dates yet).
    `progress(done, total, bytes, workers)` is called as each copy completes:
    `total` = copies being fetched this run, `done` = cumulative completed,
    `bytes` = cumulative bytes, `workers` = current adaptive concurrency.
    Raises AuthError if the token is rejected."""
    when: dict[str, dt.datetime] = {}
    fetch: dict[str, list[str]] = {}
    cached = 0
    for fid, paths in need.items():
        have = get_exif_dates(conn, fid) if conn is not None else {}
        for p in paths:
            if p in have:
                cached += 1
                if have[p]:
                    when[p] = have[p]
            else:
                fetch.setdefault(fid, []).append(p)

    uncached = sum(len(v) for v in fetch.values())
    if not (headers and fetch):
        return when, {"cached": cached, "fetched": 0,
                      "uncached": uncached, "bytes": 0}

    token = headers.get("Authorization", "").split("Bearer ")[-1].strip()
    session = make_session(token, max_workers)
    limiter = AdaptiveLimiter(start=4, maximum=max_workers)

    stats = {"fetched": 0, "bytes": 0}

    def record(fid, path, date, nbytes):
        """Main-thread only: persist one result, update `when`/progress/stats."""
        if conn is not None:
            put_exif_dates(conn, fid, [(path, date)])
        if date:
            when[path] = date
        stats["fetched"] += 1
        stats["bytes"] += nbytes
        if progress:
            progress(stats["fetched"], uncached, stats["bytes"], int(limiter.limit))

    # 1) Build a single-GET job (fid, path, header_offset, name_len) per candidate.
    #    Offsets come from the cache for free; only parts whose offsets aren't
    #    cached (legacy cache / fresh index) need a central-directory read, and
    #    those are done concurrently and backfilled so later runs skip the network.
    jobs: list[tuple[str, str, int, int]] = []
    backfill: list[tuple[str, list[str], dict]] = []   # (fid, paths, cached_offsets)
    for fid, paths in fetch.items():
        offs = get_entry_offsets(conn, fid) if conn is not None else {}
        if all(p in offs for p in paths):
            for p in paths:
                jobs.append((fid, p, offs[p], len(p.encode("utf-8"))))
        else:
            backfill.append((fid, paths, offs))

    if backfill:
        def read_offsets(fid):
            entries, nbytes = read_part_entries(fid, headers)
            return fid, {n: off for n, _, off in entries}, nbytes

        parts_total = len(backfill)
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(read_offsets, fid): (fid, paths)
                    for fid, paths, _ in backfill}
            for parts_done, fut in enumerate(as_completed(futs), start=1):
                fid, paths = futs[fut]
                _, offs, nbytes = fut.result()
                if conn is not None and offs:
                    put_entry_offsets(conn, fid, offs)   # main-thread persist
                for p in paths:
                    if p in offs:
                        jobs.append((fid, p, offs[p], len(p.encode("utf-8"))))
                    else:
                        record(fid, p, None, 0)          # path not in this zip
                stats["bytes"] += nbytes
                if on_gather:
                    on_gather(parts_done, parts_total, stats["bytes"])

    # 2) Fetch the STORED heads in parallel with AIMD concurrency + retry/backoff.
    def worker(job):
        fid, path, offset, name_len = job
        for _ in range(MAX_TRIES):
            with limiter.slot():
                try:
                    head_bytes, nbytes = fetch_head(session, fid, offset, name_len)
                    limiter.on_success()
                    date = read_exif_datetime(head_bytes) if head_bytes else None
                    return fid, path, date, nbytes
                except RateLimited as exc:
                    limiter.on_rate_limited(exc.retry_after)
                except TransientError:
                    pass
        return fid, path, None, 0          # gave up — leave the group unconfirmed

    if jobs:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [ex.submit(worker, j) for j in jobs]
            try:
                for fut in as_completed(futures):
                    record(*fut.result())   # AuthError (fatal) re-raises here
            except AuthError:
                for f in futures:
                    f.cancel()
                raise

    return when, {"cached": cached, "fetched": stats["fetched"],
                  "uncached": 0, "bytes": stats["bytes"]}


def real_dup_pairs(group, when, tol=TOL):
    """Confirm real duplicates within one same-name group via time-clustering.

    `group` is [(path, size)]; `when` maps path -> datetime. Returns a list of
    pairs (time-clusters with >=2 distinct sizes), each a dict:
        when    -- the cluster's capture instant (earliest copy)
        sizes   -- ascending copy sizes
        keep    -- smallest size (the keep target)
        reclaim -- bytes freed if only the smallest is kept
        copies  -- [(path, size)] in the cluster
    Copies with no known date are ignored (can't be confirmed)."""
    timed = [(when[p], (p, s)) for p, s in group if p in when]
    pairs = []
    for cluster in cluster_by_time(timed, tol):
        copies = [payload for _, payload in cluster]
        sizes = sorted(s for _, s in copies)
        if len(set(sizes)) < 2:
            continue
        pairs.append({
            "when": cluster[0][0],
            "sizes": sizes,
            "keep": sizes[0],
            "reclaim": sum(sizes[1:]),
            "copies": copies,
        })
    return pairs
