import io
import zipfile

from gpdedup.central_dir import entries_from_zipfile


def test_entries_from_zipfile_matches_getinfo():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Photos from 2015/001.JPG", b"a" * 1000)
        zf.writestr("Trip/002.JPG", b"b" * 2000)
        zf.mkdir("emptydir") if hasattr(zf, "mkdir") else None

    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zf:
        entries = entries_from_zipfile(zf)
        by_name = {n: (s, off) for n, s, off in entries}
        # every non-dir entry is present with the size + offset zipfile reports
        for name in ("Photos from 2015/001.JPG", "Trip/002.JPG"):
            zi = zf.getinfo(name)
            assert by_name[name] == (zi.file_size, zi.header_offset)
        # directories are excluded
        assert all(not n.endswith("/") for n, _, _ in entries)
