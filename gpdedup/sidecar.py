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

from .grouping import _COLLISION, MEDIA_EXTENSIONS

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
