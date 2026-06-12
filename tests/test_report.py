import base64
import datetime as dt

from gpdedup.grouping import is_album_path, summarize_group
from gpdedup.report import (
    album_actions, build_model, combined_search_url, or_search_url,
    search_url, token_search_url, write_html, write_table_html,
)


def test_token_search_url_preserves_literal_name():
    # underscores + UUID must survive verbatim inside the encoded token
    name = "original_25b90592-d8da-46d6-bd1c-3d9f43fc0d43_P"
    url = token_search_url([name])
    tok = url.rsplit("/", 1)[-1]
    raw = base64.urlsafe_b64decode(tok + "=" * (-len(tok) % 4))
    assert name.encode() in raw                      # literal, not tokenized to "originalP"
    assert raw.startswith(b"\n")                      # field 1, length-delimited


def test_is_album_path():
    assert not is_album_path("Takeout/Google Photos/Photos from 2014/IMG_0001.JPG")
    assert is_album_path("Takeout/Google Photos/Vacation 2014/IMG_0001.JPG")


def test_summarize_keeps_smallest_and_collects_albums():
    items = [
        ("Photos from 2014/IMG_0001.JPG", 1_386_337),
        ("Vacation 2014/IMG_0001.JPG", 1_386_337),       # album copy of the big one
        ("Photos from 2014/IMG_0001(1).JPG", 549_197),   # smaller dupe
    ]
    clusters = summarize_group(items)
    assert [c["size"] for c in clusters] == [549_197, 1_386_337]
    assert clusters[0]["keeper"] is True          # smallest kept
    assert clusters[1]["keeper"] is False
    assert clusters[1]["albums"] == ["Vacation 2014"]


def test_search_url_quotes_filename():
    assert search_url("IMG_0001.JPG") == \
        "https://photos.google.com/search/%22IMG_0001.JPG%22"


def test_album_action_when_deleted_copy_is_in_album(tmp_path):
    # the to-be-deleted (larger) copy is in an album -> keeper must be added there
    candidates = {
        "IMG_0001.JPG": [
            ("Photos from 2014/IMG_0001(1).JPG", 549_197),
            ("Vacation 2014/IMG_0001.JPG", 1_386_337),
        ]
    }
    model = build_model(candidates)
    assert model[0]["albums"] == ["Vacation 2014"]

    out = tmp_path / "r.html"
    stats = write_html(candidates, str(out))
    assert stats == {"groups": 1, "reclaim": 1_386_337, "album_actions": 1}
    text = out.read_text()
    assert "photos.google.com/search/%22IMG_0001.JPG%22" in text
    assert "Vacation 2014" in text


def test_album_action_includes_group_even_if_keeper_already_in_album():
    # keeper (smaller) is itself in the album too -> still listed (harmless re-add)
    candidates = {
        "IMG_0002.JPG": [
            ("Trip/IMG_0002(1).JPG", 100),   # keeper, already in album
            ("Trip/IMG_0002.JPG", 200),      # deleted, also in album
        ]
    }
    actions = album_actions(build_model(candidates))
    assert actions == {"Trip": ["IMG_0002.JPG"]}


def test_album_actions_group_by_album():
    candidates = {
        "IMG_6808.JPG": [("Photos from 2014/IMG_6808(1).JPG", 100),
                         ("Trip/IMG_6808.JPG", 200)],
        "IMG_6885.JPG": [("Photos from 2014/IMG_6885(1).JPG", 100),
                         ("Trip/IMG_6885.JPG", 200)],
        "IMG_9999.JPG": [("Photos from 2014/IMG_9999(1).JPG", 100),
                         ("Photos from 2014/IMG_9999.JPG", 200)],  # no album -> no action
    }
    actions = album_actions(build_model(candidates))
    assert actions == {"Trip": ["IMG_6808.JPG", "IMG_6885.JPG"]}


def test_combined_search_url_quoted_stems_joined_by_or():
    # ad-hoc helper only (combined search is unreliable in Google Photos)
    url = combined_search_url(["IMG_6808.JPG", "IMG_6885.JPG"])
    assert url == ("https://photos.google.com/search/"
                   "%22IMG_6808%22%20OR%20%22IMG_6885%22")


def test_or_search_url_quotes_and_ors_raw_terms():
    url = or_search_url(["IMG_6799", "IMG_6813"])
    assert url == ("https://photos.google.com/search/"
                   "%22IMG_6799%22%20OR%20%22IMG_6813%22")


def test_write_table_html_one_row_per_group_with_pairs(tmp_path):
    rows = [{
        "name": "001.JPG",
        "search_url": "https://photos.google.com/search/TOKEN",
        "pairs": [
            {"when": dt.datetime(2015, 1, 4, 11, 10, 25),
             "sizes": [452_864, 3_869_719], "keep": 452_864, "reclaim": 3_869_719},
            {"when": dt.datetime(2015, 3, 19, 18, 15, 14),
             "sizes": [542_381, 4_189_073], "keep": 542_381, "reclaim": 4_189_073},
        ],
        "reclaim": 3_869_719 + 4_189_073,
    }]
    out = tmp_path / "t.html"
    stats = write_table_html(rows, str(out))
    assert stats == {"rows": 1, "reclaim": 3_869_719 + 4_189_073}
    text = out.read_text()
    assert text.count("<tr>") == 2                  # 1 header + 1 group row
    assert "https://photos.google.com/search/TOKEN" in text
    assert "2015-01-04 11:10" in text and "2015-03-19 18:15" in text  # both pair dates
    assert "452,864 B" in text and "keep" in text


def test_write_table_html_links_each_copy_to_its_deep_link(tmp_path):
    rows = [{
        "name": "001.JPG",
        "search_url": "https://photos.google.com/search/TOKEN",
        "pairs": [{
            "when": dt.datetime(2015, 1, 4, 11, 10, 25),
            "sizes": [452_864, 3_869_719], "keep": 452_864, "reclaim": 3_869_719,
            "copies": [("Photos from 2015/001(6).JPG", 452_864),
                       ("Photos from 2015/001(1).JPG", 3_869_719)],
        }],
        "reclaim": 3_869_719,
    }]
    url_by_path = {
        "Photos from 2015/001(6).JPG": "https://photos.google.com/photo/SMALL",
        "Photos from 2015/001(1).JPG": "https://photos.google.com/photo/BIG",
    }
    out = tmp_path / "t.html"
    write_table_html(rows, str(out), url_by_path)
    text = out.read_text()
    # each size is now an anchor to its OWN distinct copy (the disambiguation)
    assert '<a href="https://photos.google.com/photo/SMALL" target="_blank">452,864 B</a>' in text
    assert '<a href="https://photos.google.com/photo/BIG" target="_blank">3,869,719 B</a>' in text
    assert "keep" in text                            # smallest still tagged
