from gpdedup.grouping import group_candidates, is_media_file, normalize_base_name


def test_is_media_file_excludes_sidecars():
    assert is_media_file("Photos from 2014/IMG_0001.JPG")
    assert is_media_file("Photos from 2014/VID_0001.mp4")
    assert not is_media_file("Photos from 2014/IMG_0001.JPG.supplemental-metadata.json")
    assert not is_media_file("Photos from 2014/metadata.json")


def test_normalize_strips_collision_suffix_and_dir():
    base = "Takeout/Google Photos/Photos from 2014/IMG_0001.JPG"
    dup = "Takeout/Google Photos/Photos from 2014/IMG_0001(1).JPG"
    assert normalize_base_name(base) == "IMG_0001.JPG"
    assert normalize_base_name(dup) == "IMG_0001.JPG"


def test_normalize_keeps_plain_name():
    assert normalize_base_name("a/b/photo.jpg") == "photo.jpg"
    assert normalize_base_name("VID_2014(12).MP4") == "VID_2014.MP4"


def test_candidates_need_two_different_sizes():
    entries = [
        # real duplicate pair: same name, different size
        ("Photos from 2014/IMG_0001.JPG", 1_386_337),
        ("Photos from 2014/IMG_0001(1).JPG", 549_197),
        # byte-identical album copy: same name AND size -> album membership, not a dupe
        ("Vacation 2014/IMG_0001.JPG", 1_386_337),
        # a unique photo
        ("Photos from 2014/IMG_0002.JPG", 800_000),
    ]
    candidates = group_candidates(entries)
    assert set(candidates) == {"IMG_0001.JPG"}
    assert len(candidates["IMG_0001.JPG"]) == 3  # all three copies kept in the group
