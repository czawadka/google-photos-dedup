import json

from gpdedup.sidecar import (
    candidate_sidecar_names, is_sidecar, match_sidecar, url_from_sidecar_bytes,
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
