import datetime as dt
import io
import zipfile

from gpdedup.drive_fetch import head_from_blob
from gpdedup.exif import read_exif_datetime
from test_exif import _build_jpeg_with_exif


def _zip_blob_at_entry(jpeg: bytes, name: str, compression: int):
    """Build a one-entry zip and return (raw_zip, blob_from_local_header)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        zf.writestr(name, jpeg)
    raw = buf.getvalue()
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        zi = zf.getinfo(name)
    return raw, raw[zi.header_offset:]


def test_stored_head_extracts_jpeg_and_dates():
    jpeg = _build_jpeg_with_exif("2015:01:04 11:10:25", "<")
    _, blob = _zip_blob_at_entry(jpeg, "Photos from 2015/001.JPG", zipfile.ZIP_STORED)
    head = head_from_blob(blob, head=64 * 1024)
    # The stored bytes start right after the local header. For this tiny entry
    # the 64 KB slice runs past the data into the trailing central directory —
    # harmless: the JPEG (and its EXIF) sits at the front and parses fine.
    assert head[:len(jpeg)] == jpeg
    assert read_exif_datetime(head) == dt.datetime(2015, 1, 4, 11, 10, 25)


def test_stored_head_truncates_to_requested_size():
    jpeg = _build_jpeg_with_exif("2015:03:19 18:15:14", ">")
    _, blob = _zip_blob_at_entry(jpeg, "x.JPG", zipfile.ZIP_STORED)
    head = head_from_blob(blob, head=16)
    assert head == jpeg[:16]


def test_deflated_head_inflates_and_dates():
    # Google Takeout DEFLATEs entries — the head must be raw-inflated, not sliced.
    jpeg = _build_jpeg_with_exif("2015:03:19 18:15:14", "<") + b"\x00" * 4000
    _, blob = _zip_blob_at_entry(jpeg, "x.JPG", zipfile.ZIP_DEFLATED)
    head = head_from_blob(blob, head=64 * 1024)
    assert head[:len(jpeg)] == jpeg
    assert read_exif_datetime(head) == dt.datetime(2015, 3, 19, 18, 15, 14)


def test_deflated_head_bounded_to_requested_size():
    jpeg = _build_jpeg_with_exif("2015:01:02 16:10:34", ">") + b"\x00" * 4000
    _, blob = _zip_blob_at_entry(jpeg, "x.JPG", zipfile.ZIP_DEFLATED)
    head = head_from_blob(blob, head=32)
    assert head == jpeg[:32]                           # inflate stopped at 32 bytes


def test_non_local_header_returns_none():
    assert head_from_blob(b"not a zip local header") is None
