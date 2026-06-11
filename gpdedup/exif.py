"""Minimal stdlib EXIF reader — just enough to get a photo's capture date.

EXIF lives in the JPEG's APP1 segment near the start of the file (APP1 is capped
at 64 KB), so feeding this the first ~64 KB — range-read from the Takeout zip
without downloading the whole image — is enough to recover DateTimeOriginal. No
Pillow dependency; we only need a few tags.
"""

from __future__ import annotations

import datetime as dt
import struct

# EXIF tags we care about (capture time, with fallbacks).
_DATETIME_ORIGINAL = 0x9003
_DATETIME_DIGITIZED = 0x9004
_DATETIME = 0x0132
_EXIF_IFD_POINTER = 0x8769


def _parse_datetime(s: str):
    """EXIF date strings are 'YYYY:MM:DD HH:MM:SS' (naive local time)."""
    s = s.strip().strip("\x00").strip()
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y:%m:%d %H:%M", "%Y:%m:%d"):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _read_ifd(buf: bytes, base: int, ifd_off: int, bo: str, want: set, out: dict):
    """Read 12-byte entries of one IFD; collect wanted tags into `out`."""
    pos = base + ifd_off
    if pos + 2 > len(buf):
        return
    (count,) = struct.unpack(bo + "H", buf[pos:pos + 2])
    pos += 2
    for _ in range(count):
        if pos + 12 > len(buf):
            return
        tag, typ, cnt = struct.unpack(bo + "HHI", buf[pos:pos + 8])
        val_off = pos + 8
        if tag in want:
            if typ == 2:  # ASCII
                start = base + struct.unpack(bo + "I", buf[val_off:val_off + 4])[0] \
                    if cnt > 4 else val_off
                out[tag] = buf[start:start + cnt].decode("ascii", "ignore")
            elif typ == 4:  # LONG (e.g. the Exif-IFD pointer)
                out[tag] = struct.unpack(bo + "I", buf[val_off:val_off + 4])[0]
        pos += 12


def read_exif_datetime(data: bytes):
    """Return the capture datetime (naive) from a JPEG's EXIF, or None.

    `data` only needs to contain the file head (the APP1 segment)."""
    if data[:2] != b"\xff\xd8":          # not a JPEG
        return None
    i, n = 2, len(data)
    while i + 4 <= n and data[i] == 0xFF:
        marker = data[i + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seglen = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker == 0xE1 and data[i + 4:i + 10] == b"Exif\x00\x00":
            tiff = data[i + 10:i + 2 + seglen]
            return _exif_from_tiff(tiff)
        if marker == 0xDA:               # start of scan — no more headers
            break
        i += 2 + seglen
    return None


def _exif_from_tiff(tiff: bytes):
    if len(tiff) < 8 or tiff[:2] not in (b"II", b"MM"):
        return None
    bo = "<" if tiff[:2] == b"II" else ">"
    (ifd0_off,) = struct.unpack(bo + "I", tiff[4:8])
    want = {_DATETIME, _DATETIME_ORIGINAL, _DATETIME_DIGITIZED, _EXIF_IFD_POINTER}
    tags: dict = {}
    _read_ifd(tiff, 0, ifd0_off, bo, want, tags)
    if _EXIF_IFD_POINTER in tags:        # capture times live in the Exif sub-IFD
        _read_ifd(tiff, 0, tags[_EXIF_IFD_POINTER], bo, want, tags)
    for tag in (_DATETIME_ORIGINAL, _DATETIME_DIGITIZED, _DATETIME):
        if tag in tags:
            d = _parse_datetime(tags[tag])
            if d:
                return d
    return None
