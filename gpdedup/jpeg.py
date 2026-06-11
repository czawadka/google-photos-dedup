"""Minimal, dependency-free JPEG dimension reader.

Parses the JPEG marker segments to find a Start-Of-Frame (SOF) marker and reads
the width/height from it. Used in the POC to prove that a single entry extracted
via range reads is a real, readable image.
"""

from __future__ import annotations

import struct

# SOF markers carry frame dimensions; these three in the C0-CF range do NOT
# (DHT, JPG, DAC), so they must be excluded.
_NON_SOF = {0xC4, 0xC8, 0xCC}


def read_jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """Return (width, height) for JPEG bytes, or raise ValueError."""
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG (missing SOI marker)")
    i, n = 2, len(data)
    while i < n:
        if data[i] != 0xFF:
            i += 1
            continue
        while i < n and data[i] == 0xFF:  # skip fill bytes
            i += 1
        if i >= n:
            break
        marker = data[i]
        i += 1
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:  # standalone, no length
            continue
        if i + 2 > n:
            break
        seg_len = struct.unpack(">H", data[i : i + 2])[0]
        if 0xC0 <= marker <= 0xCF and marker not in _NON_SOF:
            # segment body: precision(1) height(2) width(2)
            height = struct.unpack(">H", data[i + 3 : i + 5])[0]
            width = struct.unpack(">H", data[i + 5 : i + 7])[0]
            return width, height
        i += seg_len
    raise ValueError("no SOF marker found")
