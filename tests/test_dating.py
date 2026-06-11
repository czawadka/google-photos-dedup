import datetime as dt

from gpdedup.dating import cluster_by_time, real_dup_pairs


def _d(s):
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def test_cluster_by_time_splits_on_gap():
    timed = [
        (_d("2015-01-04 11:10:25"), "a"),
        (_d("2015-01-04 11:10:25"), "b"),   # same instant -> same cluster
        (_d("2015-03-19 18:15:14"), "c"),   # months later -> new cluster
        (_d("2015-03-19 23:00:00"), "d"),   # <12h after c -> joins c's cluster
    ]
    clusters = cluster_by_time(timed)
    payloads = [[p for _, p in c] for c in clusters]
    assert payloads == [["a", "b"], ["c", "d"]]


def test_real_dup_pairs_finds_same_instant_differing_size():
    # 001.JPG-style group: two real pairs hidden among unrelated singletons.
    group = [
        ("p/001.JPG", 452_864),
        ("p/001(1).JPG", 3_869_719),
        ("p/001(2).JPG", 542_381),
        ("p/001(3).JPG", 4_189_073),
        ("p/001(4).JPG", 3_522_204),       # lone different photo, same name
    ]
    when = {
        "p/001.JPG": _d("2015-01-04 11:10:25"),
        "p/001(1).JPG": _d("2015-01-04 11:10:25"),
        "p/001(2).JPG": _d("2015-03-19 18:15:14"),
        "p/001(3).JPG": _d("2015-03-19 18:15:14"),
        "p/001(4).JPG": _d("2015-01-02 16:10:34"),
    }
    pairs = real_dup_pairs(group, when)
    assert len(pairs) == 2
    assert pairs[0]["sizes"] == [452_864, 3_869_719]
    assert pairs[0]["keep"] == 452_864
    assert pairs[0]["reclaim"] == 3_869_719
    assert pairs[0]["when"] == _d("2015-01-04 11:10:25")
    assert pairs[1]["sizes"] == [542_381, 4_189_073]


def test_no_pair_when_same_name_but_different_dates():
    # generic-name false positive: same size-difference, but taken months apart
    group = [("p/006.JPG", 4_247_409), ("p/006(1).JPG", 5_161_965)]
    when = {
        "p/006.JPG": _d("2015-01-04 11:16:16"),
        "p/006(1).JPG": _d("2015-03-19 18:20:38"),
    }
    assert real_dup_pairs(group, when) == []


def test_same_instant_but_equal_size_is_not_a_pair():
    # equal size at the same instant = album duplication, not a re-encode dupe
    group = [("a/x.JPG", 100), ("Trip/x.JPG", 100)]
    when = {"a/x.JPG": _d("2015-01-01 00:00:00"), "Trip/x.JPG": _d("2015-01-01 00:00:00")}
    assert real_dup_pairs(group, when) == []


def test_copies_without_dates_are_ignored():
    group = [("p/y.JPG", 100), ("p/y(1).JPG", 200)]
    assert real_dup_pairs(group, {"p/y.JPG": _d("2015-01-01 00:00:00")}) == []
