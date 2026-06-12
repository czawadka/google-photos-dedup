from gpdedup.grouping import (
    group_candidates,
    is_media_file,
    is_truncated_name,
    normalize_base_name,
)


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


def test_is_truncated_name():
    # original_<uuid>_<orig>.jpg truncated by Takeout to exactly 51 chars
    truncated = "original_8f58dc51-fa77-40b8-96f3-95f73292dfbe_P.jpg"
    assert len(truncated) == 51
    assert is_truncated_name(truncated)
    # its (1) sibling normalizes back to the same 51-char name -> also truncated
    assert is_truncated_name(normalize_base_name(
        "Photos from 2022/original_8f58dc51-fa77-40b8-96f3-95f73292dfbe_P(1).jpg"))
    # ordinary Picasa-era names are short -> not truncated
    assert not is_truncated_name("IMG_0001.JPG")
    assert not is_truncated_name("001.JPG")


def test_truncated_clash_group_is_excluded():
    # Two distinct derived files collapse to one truncated name (Takeout adds (1));
    # they look like a different-size dupe but must be dropped as a false positive.
    uuid = "8f58dc51-fa77-40b8-96f3-95f73292dfbe"
    entries = [
        (f"Photos from 2022/original_{uuid}_P.jpg", 3_650_274),
        (f"Photos from 2022/original_{uuid}_P(1).jpg", 2_747_163),
        # a genuine short-name dupe pair that must survive
        ("Photos from 2014/IMG_0001.JPG", 1_386_337),
        ("Photos from 2014/IMG_0001(1).JPG", 549_197),
    ]
    candidates = group_candidates(entries)
    survivors = {n for n in candidates if not is_truncated_name(n)}
    assert survivors == {"IMG_0001.JPG"}
    assert is_truncated_name(f"original_{uuid}_P.jpg")  # the dropped one


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
