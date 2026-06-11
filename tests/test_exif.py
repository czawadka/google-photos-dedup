import datetime as dt
import struct

from gpdedup.exif import read_exif_datetime


def _build_jpeg_with_exif(date_str: str, byte_order: str = "<") -> bytes:
    """Construct a minimal JPEG head: SOI + APP1(Exif) carrying DateTimeOriginal."""
    bo = byte_order
    ascii_bytes = date_str.encode("ascii") + b"\x00"   # 20 bytes for a full datetime

    # TIFF: header (8) + IFD0 + Exif-IFD + the ascii string.
    ifd0_off = 8
    exif_ifd_off = ifd0_off + 2 + 12 + 4               # after IFD0 (1 entry) + next-ptr
    str_off = exif_ifd_off + 2 + 12 + 4                # after Exif-IFD (1 entry) + next-ptr

    tiff = bytearray()
    tiff += b"II" if bo == "<" else b"MM"
    tiff += struct.pack(bo + "HI", 42, ifd0_off)

    # IFD0: one entry — the Exif-IFD pointer (tag 0x8769, type LONG)
    tiff += struct.pack(bo + "H", 1)
    tiff += struct.pack(bo + "HHII", 0x8769, 4, 1, exif_ifd_off)
    tiff += struct.pack(bo + "I", 0)                   # next IFD = none

    # Exif-IFD: one entry — DateTimeOriginal (tag 0x9003, type ASCII)
    tiff += struct.pack(bo + "H", 1)
    tiff += struct.pack(bo + "HHII", 0x9003, 2, len(ascii_bytes), str_off)
    tiff += struct.pack(bo + "I", 0)
    assert len(tiff) == str_off
    tiff += ascii_bytes

    payload = b"Exif\x00\x00" + bytes(tiff)
    app1 = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    return b"\xff\xd8" + app1 + b"\xff\xd9"


def test_reads_datetime_original_little_endian():
    data = _build_jpeg_with_exif("2015:01:03 09:19:24", "<")
    assert read_exif_datetime(data) == dt.datetime(2015, 1, 3, 9, 19, 24)


def test_reads_datetime_original_big_endian():
    data = _build_jpeg_with_exif("2015:03:15 14:30:02", ">")
    assert read_exif_datetime(data) == dt.datetime(2015, 3, 15, 14, 30, 2)


def test_non_jpeg_returns_none():
    assert read_exif_datetime(b"\x89PNG\r\n\x1a\n....") is None


def test_jpeg_without_exif_returns_none():
    assert read_exif_datetime(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01....") is None
