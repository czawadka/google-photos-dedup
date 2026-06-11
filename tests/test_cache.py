import datetime as dt
import sqlite3

from gpdedup.cache import (
    get_entries,
    get_entry_offsets,
    get_exif_dates,
    get_parts,
    open_cache,
    put_entries,
    put_entry_offsets,
    put_exif_dates,
)


def test_roundtrip_and_offline_parts(tmp_path):
    conn = open_cache(str(tmp_path / "c.sqlite"))
    entries = [("Photos from 2014/IMG_0001.JPG", 100, 0),
               ("Trip/IMG_0001.JPG", 200, 4096)]
    put_entries(conn, "fid1", "takeout-001.zip", 2_000_000_000, "2026-06-11T00:00:00Z", entries)

    assert get_entries(conn, "fid1", 2_000_000_000, "2026-06-11T00:00:00Z") == entries
    assert get_parts(conn) == [
        {"id": "fid1", "name": "takeout-001.zip",
         "size": 2_000_000_000, "modifiedTime": "2026-06-11T00:00:00Z"}
    ]


def test_invalidates_on_changed_size_or_mtime(tmp_path):
    conn = open_cache(str(tmp_path / "c.sqlite"))
    put_entries(conn, "fid1", "p.zip", 100, "t1", [("a.jpg", 1, 0)])
    assert get_entries(conn, "fid1", 100, "t1") is not None
    assert get_entries(conn, "fid1", 999, "t1") is None      # size changed
    assert get_entries(conn, "fid1", 100, "t2") is None      # mtime changed
    assert get_entries(conn, "missing", 100, "t1") is None


def test_entry_offsets_roundtrip_and_backfill(tmp_path):
    conn = open_cache(str(tmp_path / "c.sqlite"))
    # one row with an offset, one without (legacy-style)
    put_entries(conn, "fid1", "p.zip", 100, "t1",
                [("a.jpg", 1, 512), ("b.jpg", 2, None)])
    assert get_entry_offsets(conn, "fid1") == {"a.jpg": 512}   # NULL omitted

    put_entry_offsets(conn, "fid1", {"b.jpg": 9000})           # UPDATE-only backfill
    assert get_entry_offsets(conn, "fid1") == {"a.jpg": 512, "b.jpg": 9000}


def test_backfill_offsets_keeps_cached_dates(tmp_path):
    conn = open_cache(str(tmp_path / "c.sqlite"))
    put_entries(conn, "fid1", "p.zip", 100, "t1", [("a.jpg", 1, None)])
    put_exif_dates(conn, "fid1", [("a.jpg", dt.datetime(2015, 1, 1))])
    put_entry_offsets(conn, "fid1", {"a.jpg": 4096})           # must not wipe dates
    assert get_exif_dates(conn, "fid1") == {"a.jpg": dt.datetime(2015, 1, 1)}


def test_migrates_legacy_entries_table(tmp_path):
    # Simulate a cache created before header_offset existed.
    path = str(tmp_path / "legacy.sqlite")
    legacy = sqlite3.connect(path)
    legacy.execute("CREATE TABLE entries(file_id TEXT, name TEXT, size INTEGER)")
    legacy.execute("INSERT INTO entries VALUES('fid1','a.jpg',1)")
    legacy.commit()
    legacy.close()

    conn = open_cache(path)                                    # adds the column
    cols = {r[1] for r in conn.execute("PRAGMA table_info(entries)")}
    assert "header_offset" in cols
    assert get_entry_offsets(conn, "fid1") == {}               # legacy row → NULL


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
    put_entries(conn, "fid1", "p.zip", 100, "t1", [("a.jpg", 1, 0)])
    put_exif_dates(conn, "fid1", [("a.jpg", dt.datetime(2015, 1, 1))])
    assert get_exif_dates(conn, "fid1")            # present

    put_entries(conn, "fid1", "p.zip", 200, "t2", [("a.jpg", 1, 0)])  # part changed
    assert get_exif_dates(conn, "fid1") == {}      # stale dates cleared
