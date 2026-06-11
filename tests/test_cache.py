from gpdedup.cache import get_entries, get_parts, open_cache, put_entries


def test_roundtrip_and_offline_parts(tmp_path):
    conn = open_cache(str(tmp_path / "c.sqlite"))
    entries = [("Photos from 2014/IMG_0001.JPG", 100), ("Trip/IMG_0001.JPG", 200)]
    put_entries(conn, "fid1", "takeout-001.zip", 2_000_000_000, "2026-06-11T00:00:00Z", entries)

    assert get_entries(conn, "fid1", 2_000_000_000, "2026-06-11T00:00:00Z") == entries
    assert get_parts(conn) == [
        {"id": "fid1", "name": "takeout-001.zip",
         "size": 2_000_000_000, "modifiedTime": "2026-06-11T00:00:00Z"}
    ]


def test_invalidates_on_changed_size_or_mtime(tmp_path):
    conn = open_cache(str(tmp_path / "c.sqlite"))
    put_entries(conn, "fid1", "p.zip", 100, "t1", [("a.jpg", 1)])
    assert get_entries(conn, "fid1", 100, "t1") is not None
    assert get_entries(conn, "fid1", 999, "t1") is None      # size changed
    assert get_entries(conn, "fid1", 100, "t2") is None      # mtime changed
    assert get_entries(conn, "missing", 100, "t1") is None
