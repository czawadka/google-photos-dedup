"""Match a Takeout media file to its sidecar JSON and pull the photo `url`.

Each photo in a Takeout export has a sidecar like
``IMG_1234.JPG.supplemental-metadata.json`` carrying a ``url`` field, e.g.
``https://photos.google.com/photo/AF1Qip...`` — a deep link to *that specific
library item*. That's the only place a per-copy link exists, so to point at the
exact copy to delete we read the sidecar belonging to that copy.

The tricky part is the filename pairing. Takeout renames in-folder collisions by
appending ``(N)``, and that marker can land in either of two places on the
sidecar:

  media   ``IMG_1234(1).JPG``
  sidecar ``IMG_1234(1).JPG.supplemental-metadata.json``   (N on the media stem)
       or ``IMG_1234.JPG.supplemental-metadata(1).json``   (N on the sidecar tail)

plus Google truncates long sidecar names (``.supplemental-metadata`` ->
``.supplemental-met`` ...). So we generate the likely names and keep whichever
actually exists in the archive's entry list, with a last-resort prefix fallback.
"""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from .cache import get_entries, get_parts, get_sidecar_urls, put_sidecar_urls
from .concurrency import AdaptiveLimiter
from .drive_fetch import (
    AuthError, RateLimited, TransientError, fetch_head, make_session,
)
from .grouping import _COLLISION, MEDIA_EXTENSIONS

SIDECAR_HEAD = 8 * 1024        # sidecars are ~1-3 KB JSON; 8 KB covers them
MAX_TRIES = 6                  # per-sidecar attempts before recording it url-less

# Observed metadata infixes, longest first (Google truncates the long one).
_META_INFIXES = [
    ".supplemental-metadata",
    ".supplemental-metadat",
    ".supplemental-meta",
    ".supplemental-met",
    ".supplemental-me",
    ".supplemental-m",
    ".supplemental",
    ".suppl",
    "",  # very old exports: just "<name>.json"
]


def is_sidecar(name: str) -> bool:
    """True for a Takeout per-photo metadata sidecar (a ``*.json`` next to media)."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return base.endswith(".json") and base != "metadata.json"


def _split_dir(path: str) -> tuple[str, str]:
    p = path.replace("\\", "/")
    return (p.rsplit("/", 1)[0] + "/", p.rsplit("/", 1)[-1]) if "/" in p else ("", p)


def _split_collision(fname: str) -> tuple[str, str]:
    """'IMG_1234(1).JPG' -> ('IMG_1234.JPG', '(1)'); 'IMG_1234.JPG' -> (.., '')."""
    root, ext = os.path.splitext(fname)
    m = _COLLISION.match(root)
    if m:
        return m.group("stem") + ext, f"({m.group('n')})"
    return fname, ""


def candidate_sidecar_names(media_path: str) -> list[str]:
    """Ordered list of plausible sidecar paths for a media file (best first)."""
    folder, fname = _split_dir(media_path)
    base, dupe = _split_collision(fname)
    out: list[str] = []
    for meta in _META_INFIXES:
        if dupe:
            # tail convention: IMG_1234.JPG.supplemental-metadata(1).json
            out.append(f"{folder}{base}{meta}{dupe}.json")
            # stem convention: IMG_1234(1).JPG.supplemental-metadata.json
            out.append(f"{folder}{fname}{meta}.json")
        else:
            out.append(f"{folder}{base}{meta}.json")
    # de-dup while preserving order
    seen: set[str] = set()
    return [c for c in out if not (c in seen or seen.add(c))]


def _media_filename(core: str) -> str | None:
    """In a sidecar core like 'IMG_1(1).JPG.supplemental-metadata', return the
    media filename 'IMG_1(1).JPG' — i.e. up to the leftmost real media extension."""
    for m in re.finditer(r"\.([A-Za-z0-9]+)", core):
        if "." + m.group(1).lower() in MEDIA_EXTENSIONS:
            nxt = core[m.end():m.end() + 1]
            if nxt in ("", ".", "("):
                return core[: m.end()]
    return None


def media_key(media_path: str) -> tuple[str, str, str]:
    """Identity of a media file independent of where the (N) collision marker
    sits: (folder, base-filename-without-(N), '(N)'-or-'')."""
    folder, fname = _split_dir(media_path)
    base, dupe = _split_collision(fname)
    return (folder, base, dupe)


def sidecar_media_key(sidecar_path: str) -> tuple[str, str, str] | None:
    """Reverse a sidecar name to the media key it describes, tolerant of any
    metadata suffix and of the (N) marker on either the stem or the tail."""
    folder, fname = _split_dir(sidecar_path)
    if not fname.lower().endswith(".json"):
        return None
    core = fname[:-5]
    tail = ""
    m = _COLLISION.match(core)            # trailing (N) -> tail-convention collision
    if m:
        core, tail = m.group("stem"), m.group("n")
    mfn = _media_filename(core)
    if not mfn:
        return None
    base, dupe = _split_collision(mfn)    # or (N) sat on the media stem
    return (folder, base, dupe or (f"({tail})" if tail else ""))


def build_sidecar_index(entry_names) -> dict[tuple[str, str, str], str]:
    """Map media key -> sidecar path for every sidecar in the archive."""
    index: dict[tuple[str, str, str], str] = {}
    for name in entry_names:
        if not is_sidecar(name):
            continue
        key = sidecar_media_key(name)
        if key is not None:
            index.setdefault(key, name)
    return index


def match_sidecar(media_path: str, entries) -> str | None:
    """Sidecar path for ``media_path``. ``entries`` may be a prebuilt index (from
    ``build_sidecar_index``) or a raw set of entry names."""
    index = entries if isinstance(entries, dict) else build_sidecar_index(entries)
    return index.get(media_key(media_path))


def url_from_sidecar_bytes(raw: bytes) -> str | None:
    """Extract the photos.google.com deep link from sidecar JSON bytes."""
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    url = data.get("url")
    return url if isinstance(url, str) and url.startswith("http") else None


def build_sidecar_offsets(conn) -> dict[tuple[str, str, str], tuple[str, str, int]]:
    """Cross-part index {media_key: (sidecar_path, file_id, header_offset)} built
    purely from the cache — sidecars live in *different* parts than their media, so
    we union every cached part's sidecar entries. Entries whose offset isn't cached
    are skipped (a fresh index/legacy cache would need a central-dir read first)."""
    index: dict[tuple[str, str, str], tuple[str, str, int]] = {}
    for part in get_parts(conn):
        entries = get_entries(conn, part["id"], part["size"], part["modifiedTime"])
        if not entries:
            continue
        for name, _size, off in entries:
            if off is None or not is_sidecar(name):
                continue
            key = sidecar_media_key(name)
            if key is not None:
                index.setdefault(key, (name, part["id"], off))
    return index


def resolve_urls(conn, media_paths, headers=None, max_workers=20, progress=None,
                 _fetch=None) -> dict[str, str]:
    """Resolve each media copy's Google Photos deep link from its sidecar `url`.

    `media_paths` is an iterable of media file paths — pass only the date-confirmed
    duplicate copies (a unique photo never needs a link). Returns {media_path: url}
    (paths with no resolvable url are simply absent). Cache-first; uncached paths
    are resolved by range-reading the matching sidecar (located via the cross-part
    offset index) only when `headers` is provided, in parallel over a pooled
    keep-alive session with adaptive concurrency. Every result is persisted as it
    lands, so an interrupt loses nothing and a re-run resumes.

    `_fetch(file_id, header_offset, name_len) -> bytes | None` overrides the network
    fetch (tests). `progress(done, total, workers)` is called as each completes.
    Raises AuthError if the token is rejected."""
    paths = list(dict.fromkeys(media_paths))           # de-dup, preserve order
    urls: dict[str, str] = {}
    have = get_sidecar_urls(conn, paths) if conn is not None else {}
    todo = []
    for p in paths:
        if p in have:
            if have[p]:
                urls[p] = have[p]
        else:
            todo.append(p)

    if not todo or (headers is None and _fetch is None):
        return urls

    # Map each uncached copy to its sidecar's part+offset; copies with no sidecar
    # are recorded as url-less so they aren't retried.
    index = build_sidecar_offsets(conn) if conn is not None else {}
    jobs: list[tuple[str, str, str, int]] = []          # (media_path, sidecar, fid, off)
    for p in todo:
        hit = index.get(media_key(p))
        if hit is None:
            if conn is not None:
                put_sidecar_urls(conn, [(p, None)])
        else:
            sidecar_path, fid, off = hit
            jobs.append((p, sidecar_path, fid, off))
    if not jobs:
        return urls

    if _fetch is None:
        token = headers.get("Authorization", "").split("Bearer ")[-1].strip()
        session = make_session(token, max_workers)

        def _fetch(file_id, header_offset, name_len):
            head_bytes, _ = fetch_head(session, file_id, header_offset, name_len,
                                       head=SIDECAR_HEAD)
            return head_bytes

    limiter = AdaptiveLimiter(start=4, maximum=max_workers)
    done = {"n": 0}

    def record(media_path, url):
        if conn is not None:
            put_sidecar_urls(conn, [(media_path, url)])
        if url:
            urls[media_path] = url
        done["n"] += 1
        if progress:
            progress(done["n"], len(jobs), int(limiter.limit))

    def worker(job):
        media_path, sidecar_path, fid, off = job
        name_len = len(sidecar_path.encode("utf-8"))
        for _ in range(MAX_TRIES):
            with limiter.slot():
                try:
                    raw = _fetch(fid, off, name_len)
                    limiter.on_success()
                    return media_path, (url_from_sidecar_bytes(raw) if raw else None)
                except RateLimited as exc:
                    limiter.on_rate_limited(exc.retry_after)
                except TransientError:
                    pass
        return media_path, None             # gave up — leave this copy unlinked

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(worker, j) for j in jobs]
        try:
            for fut in as_completed(futures):
                record(*fut.result())       # AuthError (fatal) re-raises here
        except AuthError:
            for f in futures:
                f.cancel()
            raise
    return urls
