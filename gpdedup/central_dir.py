"""Read a Takeout part's ZIP central directory over HTTP Range.

The central directory (all entry names + sizes + local-header offsets) lives at
the tail of the file, so an `HttpRangeReader`-backed `zipfile.ZipFile` enumerates
every entry by transferring only kilobytes. We keep the local-header offset too —
it lets the dating pass fetch a single entry's head with one range GET later,
without re-opening the zip.

Shared by `index_parts` (the entry listing) and the `capture_dates` gather/backfill
(offsets); both fan out across parts with their own thread pool, each part on its
own reader (independent — thread-safe).
"""

from __future__ import annotations

import zipfile

from .drive import media_url
from .http_range import HttpRangeReader


def entries_from_zipfile(zf: zipfile.ZipFile):
    """[(name, size, header_offset)] for every non-directory entry."""
    return [(zi.filename, zi.file_size, zi.header_offset)
            for zi in zf.infolist() if not zi.is_dir()]


def read_part_entries(file_id: str, headers: dict):
    """Range-read one part's central directory.

    Returns (entries, bytes_downloaded) where entries is
    [(name, size, header_offset)]."""
    reader = HttpRangeReader(media_url(file_id), headers=headers)
    with zipfile.ZipFile(reader) as zf:
        entries = entries_from_zipfile(zf)
    return entries, reader.bytes_downloaded
