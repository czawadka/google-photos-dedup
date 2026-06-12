import json

from gpdedup.cache import get_sidecar_urls, open_cache, put_entries
from gpdedup.sidecar import (
    build_sidecar_offsets, candidate_sidecar_names, is_sidecar, match_sidecar,
    media_key, resolve_urls, url_from_sidecar_bytes,
)


def test_is_sidecar():
    assert is_sidecar("Photos from 2014/IMG_0001.JPG.supplemental-metadata.json")
    assert not is_sidecar("Photos from 2014/IMG_0001.JPG")
    assert not is_sidecar("Takeout/Google Photos/metadata.json")  # album-level, not per-photo


def test_match_plain_file():
    entries = {"Photos from 2014/IMG_0001.JPG.supplemental-metadata.json"}
    assert match_sidecar("Photos from 2014/IMG_0001.JPG", entries) == \
        "Photos from 2014/IMG_0001.JPG.supplemental-metadata.json"


def test_match_collision_tail_convention():
    # (1) on the sidecar tail: IMG_0001.JPG.supplemental-metadata(1).json
    entries = {"Photos from 2014/IMG_0001.JPG.supplemental-metadata(1).json"}
    assert match_sidecar("Photos from 2014/IMG_0001(1).JPG", entries) == \
        "Photos from 2014/IMG_0001.JPG.supplemental-metadata(1).json"


def test_match_collision_stem_convention():
    # (1) on the media stem: IMG_0001(1).JPG.supplemental-metadata.json
    entries = {"Photos from 2014/IMG_0001(1).JPG.supplemental-metadata.json"}
    assert match_sidecar("Photos from 2014/IMG_0001(1).JPG", entries) == \
        "Photos from 2014/IMG_0001(1).JPG.supplemental-metadata.json"


def test_match_truncated_meta_suffix():
    entries = {"Photos from 2014/IMG_0001.JPG.supplemental-met.json"}
    assert match_sidecar("Photos from 2014/IMG_0001.JPG", entries) == \
        "Photos from 2014/IMG_0001.JPG.supplemental-met.json"


def test_no_false_prefix_match_across_similar_names():
    # IMG_0001 must not grab IMG_00012's sidecar
    entries = {"Photos from 2014/IMG_00012.JPG.supplemental-metadata.json"}
    assert match_sidecar("Photos from 2014/IMG_0001.JPG", entries) is None


def test_candidate_names_are_ordered_and_unique():
    cands = candidate_sidecar_names("Photos from 2014/IMG_0001(1).JPG")
    assert len(cands) == len(set(cands))
    assert cands[0] == "Photos from 2014/IMG_0001.JPG.supplemental-metadata(1).json"


def test_match_unknown_metadata_suffix():
    # any suffix between the media extension and .json should still reverse-map
    entries = {"Photos from 2014/IMG_0001.JPG.metadata-v2-whatever.json"}
    assert match_sidecar("Photos from 2014/IMG_0001.JPG", entries) == \
        "Photos from 2014/IMG_0001.JPG.metadata-v2-whatever.json"


def test_match_old_ext_tail_collision():
    # very old convention: collision marker after the extension, no suffix
    entries = {"Photos from 2014/IMG_0001.JPG(1).json"}
    assert match_sidecar("Photos from 2014/IMG_0001(1).JPG", entries) == \
        "Photos from 2014/IMG_0001.JPG(1).json"


def test_index_disambiguates_both_copies_in_one_folder():
    entries = {
        "Trip/IMG_0001.JPG.supplemental-metadata.json",      # the non-dupe copy
        "Trip/IMG_0001.JPG.supplemental-metadata(1).json",   # the (1) dupe
    }
    assert match_sidecar("Trip/IMG_0001.JPG", entries) == \
        "Trip/IMG_0001.JPG.supplemental-metadata.json"
    assert match_sidecar("Trip/IMG_0001(1).JPG", entries) == \
        "Trip/IMG_0001.JPG.supplemental-metadata(1).json"


def test_url_from_sidecar_bytes():
    raw = json.dumps({"title": "IMG_0001.JPG",
                      "url": "https://photos.google.com/photo/AF1QipABC"}).encode()
    assert url_from_sidecar_bytes(raw) == "https://photos.google.com/photo/AF1QipABC"
    assert url_from_sidecar_bytes(b"not json") is None
    assert url_from_sidecar_bytes(json.dumps({"title": "x"}).encode()) is None


# A media copy and its sidecar live in *different* zip parts; both copies of one
# dupe pair each have their own sidecar (tail-(N) convention) at a known offset.
SC1 = "Trip/IMG_0001.JPG.supplemental-metadata.json"      # for IMG_0001.JPG
SC2 = "Trip/IMG_0001.JPG.supplemental-metadata(1).json"   # for IMG_0001(1).JPG
M1, M2 = "Trip/IMG_0001.JPG", "Trip/IMG_0001(1).JPG"


def _seed_sidecar_part(conn):
    # Sidecars indexed from a different part than the media, with header offsets.
    put_entries(conn, "part-sc", "p-sidecars.zip", 100, "t1",
                [(SC1, 10, 1000), (SC2, 20, 2000)])


def test_build_sidecar_offsets_from_cache(tmp_path):
    conn = open_cache(str(tmp_path / "c.sqlite"))
    _seed_sidecar_part(conn)
    index = build_sidecar_offsets(conn)
    assert index[media_key(M1)] == (SC1, "part-sc", 1000)
    assert index[media_key(M2)] == (SC2, "part-sc", 2000)


def test_resolve_urls_distinct_per_copy_and_cached(tmp_path):
    conn = open_cache(str(tmp_path / "c.sqlite"))
    _seed_sidecar_part(conn)
    blobs = {
        1000: json.dumps({"url": "https://photos.google.com/photo/AAA"}).encode(),
        2000: json.dumps({"url": "https://photos.google.com/photo/BBB"}).encode(),
    }
    calls = []

    def fake_fetch(file_id, header_offset, name_len):
        calls.append((file_id, header_offset, name_len))
        return blobs.get(header_offset)

    urls = resolve_urls(conn, [M1, M2], _fetch=fake_fetch)
    # each copy resolves to its OWN distinct deep link (the disambiguation point)
    assert urls == {M1: "https://photos.google.com/photo/AAA",
                    M2: "https://photos.google.com/photo/BBB"}
    assert len(calls) == 2

    # second run is cache-first: the fetcher must not be called again
    def boom(*a):
        raise AssertionError("should be served from cache")

    assert resolve_urls(conn, [M1, M2], _fetch=boom) == urls


def test_resolve_urls_records_missing_sidecar(tmp_path):
    conn = open_cache(str(tmp_path / "c.sqlite"))
    _seed_sidecar_part(conn)        # no sidecar for IMG_9999
    missing = "Trip/IMG_9999.JPG"

    def fake_fetch(file_id, header_offset, name_len):
        raise AssertionError("no sidecar -> never fetched")

    urls = resolve_urls(conn, [missing], _fetch=fake_fetch)
    assert missing not in urls
    # recorded as resolved-but-no-url so a re-run won't try again
    assert get_sidecar_urls(conn, [missing]) == {missing: None}
