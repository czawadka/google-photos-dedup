"""Filename normalization and duplicate-candidate grouping.

The Picasa-era duplicates share a base filename but differ in size. Takeout also
renames in-folder name collisions by appending ``(1)``, ``(2)`` — so to regroup
the originals we strip that suffix and the directory, then group by the result.

Within a group:
  - entries with the SAME size across different folders are byte-identical copies
    that encode album membership (NOT duplicates);
  - entries with DIFFERENT sizes are the real dedup candidates.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict

# Trailing "(123)" right before the extension, as added by Takeout on collisions.
_COLLISION = re.compile(r"^(?P<stem>.*?)\((?P<n>\d+)\)$")

# Takeout's per-year buckets hold ALL photos; any other folder is a user album.
_YEAR_FOLDER = re.compile(r"^Photos from \d{4}$")

# Real media we dedup — everything else (notably Takeout's *.json sidecars,
# metadata.json, *.html) is ignored.
MEDIA_EXTENSIONS = {
    # images
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp",
    ".heic", ".heif", ".dng", ".raw", ".cr2", ".nef", ".arw", ".orf", ".rw2", ".raf",
    # videos
    ".mp4", ".mov", ".m4v", ".3gp", ".3g2", ".avi", ".mkv", ".mpg", ".mpeg",
    ".wmv", ".flv", ".webm", ".mts", ".m2ts",
}


def is_media_file(path: str) -> bool:
    """True for photo/video files; False for .json sidecars, .html, etc."""
    return os.path.splitext(path)[1].lower() in MEDIA_EXTENSIONS


def parent_folder(path: str) -> str:
    parts = path.replace("\\", "/").split("/")
    return parts[-2] if len(parts) >= 2 else ""


def is_album_path(path: str) -> bool:
    """True if the file lives in a user album folder (not a 'Photos from <year>')."""
    folder = parent_folder(path)
    return bool(folder) and not _YEAR_FOLDER.match(folder)


def normalize_base_name(path: str) -> str:
    """'…/Photos from 2014/IMG_0001(1).JPG' -> 'IMG_0001.JPG' (case preserved)."""
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    root, ext = os.path.splitext(name)
    m = _COLLISION.match(root)
    if m:
        root = m.group("stem")
    return root + ext


def group_candidates(entries: list[tuple[str, int]]) -> dict[str, list[tuple[str, int]]]:
    """Map normalized name -> entries, keeping only groups that contain at least
    two DIFFERENT sizes (the real duplicate candidates)."""
    groups: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for path, size in entries:
        groups[normalize_base_name(path)].append((path, size))
    return {
        name: items
        for name, items in groups.items()
        if len({size for _, size in items}) > 1
    }


def summarize_group(items: list[tuple[str, int]]) -> list[dict]:
    """Cluster a candidate group's entries by size (each distinct size = one
    library media item) with its album memberships. Smallest is the keeper."""
    by_size: dict[int, dict] = {}
    for path, size in items:
        rec = by_size.setdefault(size, {"size": size, "paths": [], "albums": set()})
        rec["paths"].append(path)
        if is_album_path(path):
            rec["albums"].add(parent_folder(path))
    clusters = sorted(by_size.values(), key=lambda c: c["size"])
    for i, c in enumerate(clusters):
        c["keeper"] = i == 0  # keep the smallest
        c["albums"] = sorted(c["albums"])
    return clusters
