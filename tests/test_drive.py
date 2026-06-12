from gpdedup.drive import TAKEOUT_QUERY, with_trashed_filter


def test_appends_trashed_guard_when_missing():
    assert with_trashed_filter("name contains 'takeout-2026-3-'") == \
        "name contains 'takeout-2026-3-' and trashed = false"


def test_leaves_query_with_trashed_untouched():
    assert with_trashed_filter(TAKEOUT_QUERY) == TAKEOUT_QUERY
    custom = "name contains 'x' and trashed = true"
    assert with_trashed_filter(custom) == custom
