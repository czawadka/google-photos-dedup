import datetime as dt

from gpdedup.cache import (
    get_entries,
    get_exif_dates,
    get_parts,
    open_cache,
    put_entries,
    put_exif_dates,
)


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


def test_exif_date_roundtrip_and_dateless(tmp_path):
    conn = open_cache(str(tmp_path / "c.sqlite"))
    when = dt.datetime(2015, 1, 4, 11, 10, 25)
    put_exif_dates(conn, "fid1", [("a.jpg", when), ("b.png", None)])

    got = get_exif_dates(conn, "fid1")
    assert got == {"a.jpg": when, "b.png": None}   # None = probed, no EXIF
    assert "a.jpg" in got and got["a.jpg"] == when
    assert get_exif_dates(conn, "other") == {}     # absent = not probed


def test_reindexing_a_part_drops_its_cached_dates(tmp_path):
    conn = open_cache(str(tmp_path / "c.sqlite"))
    put_entries(conn, "fid1", "p.zip", 100, "t1", [("a.jpg", 1)])
    put_exif_dates(conn, "fid1", [("a.jpg", dt.datetime(2015, 1, 1))])
    assert get_exif_dates(conn, "fid1")            # present

    put_entries(conn, "fid1", "p.zip", 200, "t2", [("a.jpg", 1)])  # part changed
    assert get_exif_dates(conn, "fid1") == {}      # stale dates cleared
