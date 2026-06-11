import os
import zipfile

from gpdedup.http_range import HttpRangeReader
from poc.range_server import serve_directory


def _write_zip(path):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("a/one.txt", b"x" * 5000)
        zf.writestr("b/two.txt", b"y" * 7000)


def test_partial_read_matches_and_counts_bytes(tmp_path):
    blob = tmp_path / "blob.bin"
    payload = bytes(range(256)) * 1000  # 256_000 bytes
    blob.write_bytes(payload)

    httpd, base = serve_directory(str(tmp_path))
    try:
        reader = HttpRangeReader(f"{base}/blob.bin")
        assert reader.size == len(payload)
        reader.seek(1000)
        chunk = reader.read(200)
        assert chunk == payload[1000:1200]
        assert reader.bytes_downloaded == 200
    finally:
        httpd.shutdown()


def test_zip_listing_reads_only_tail(tmp_path):
    zpath = tmp_path / "sample.zip"
    _write_zip(zpath)
    total = os.path.getsize(zpath)

    httpd, base = serve_directory(str(tmp_path))
    try:
        reader = HttpRangeReader(f"{base}/sample.zip")
        with zipfile.ZipFile(reader) as zf:
            names = sorted(i.filename for i in zf.infolist())
        assert names == ["a/one.txt", "b/two.txt"]
        # central-directory read must be far smaller than the whole archive
        assert reader.bytes_downloaded < total
    finally:
        httpd.shutdown()
