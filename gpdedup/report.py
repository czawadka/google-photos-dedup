"""Render duplicate-candidate groups as a clickable HTML worklist.

Two action batches to minimize operations:
  §1 Add-to-album, grouped by album: every keeper that must be added to a given
     album, with a combined "try" search and individual links.
  §2 Delete pass: all duplicate filenames in combined batches (open many at
     once), with per-file links.

Caveats baked into the UI: Google Photos search has no documented multi-file /
boolean operator, so combined links are best-effort (verify they return all
files); the only searchable handle is the filename (no internal-id search).
"""

from __future__ import annotations

import base64
import html
import urllib.parse
from collections import defaultdict

from .grouping import summarize_group

SEARCH_BASE = "https://photos.google.com/search/"
DELETE_BATCH = 10


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | 0x80 if n else b)
        if not n:
            return bytes(out)


def _ld(field: int, data: bytes) -> bytes:
    """A protobuf length-delimited field (wire type 2)."""
    return bytes([(field << 3) | 2]) + _varint(len(data)) + data


def search_token(query: str) -> str:
    """Build the base64 protobuf token Google Photos uses in /search/<token>.

    Observed shape: {1: <query>, 4: {1: <query>}}. Constructing it ourselves
    means Google renders the query verbatim instead of re-parsing the plaintext
    URL (which strips underscores and drops OR terms)."""
    q = query.encode("utf-8")
    msg = _ld(1, q) + _ld(4, _ld(1, q))
    return base64.urlsafe_b64encode(msg).rstrip(b"=").decode()


def token_search_url(terms: list[str]) -> str:
    """Reliable combined search: build the token directly, underscores intact."""
    query = " OR ".join(f'"{t}"' for t in terms)
    return SEARCH_BASE + search_token(query)


def search_url(filename: str) -> str:
    """Deep link to a quoted Google Photos filename search."""
    return SEARCH_BASE + urllib.parse.quote(f'"{filename}"')


def or_search_url(terms: list[str]) -> str:
    """Deep link to a quoted-OR search, e.g. '"a" OR "b"' URL-encoded.

    WARNING: verified unreliable in Google Photos — multi-term OR queries get
    their underscores stripped (IMG_8773 -> IMG8773) and the term list capped,
    yielding "No results". Kept only as an ad-hoc helper; the report uses
    per-file links instead."""
    query = " OR ".join(f'"{t}"' for t in terms)
    return SEARCH_BASE + urllib.parse.quote(query)


def combined_search_url(filenames: list[str]) -> str:
    """OR-search over base names (extension dropped), e.g. '"IMG_6799" OR
    "IMG_6813"'. Google Photos ORs quoted bare names but ANDs extension terms."""
    return or_search_url([n.rsplit(".", 1)[0] for n in filenames])


def build_model(candidates: dict[str, list[tuple[str, int]]]) -> list[dict]:
    model = []
    for name in sorted(candidates):
        clusters = summarize_group(candidates[name])
        reclaim = sum(c["size"] for c in clusters if not c["keeper"])
        # Every album any copy touches: the keeper should end up in all of them.
        albums = sorted(set().union(*(set(c["albums"]) for c in clusters)))
        model.append({
            "name": name,
            "url": search_url(name),
            "clusters": clusters,
            "reclaim": reclaim,
            "albums": albums,
        })
    return model


def album_actions(model: list[dict]) -> dict[str, list[str]]:
    """album -> keeper filenames to add. Inclusive: every group that touches the
    album is listed (re-adding a photo already in the album is harmless), so
    there's no fragile 'is it already a member?' check."""
    actions: dict[str, set] = defaultdict(set)
    for g in model:
        for a in g["albums"]:
            actions[a].add(g["name"])
    return {a: sorted(names) for a, names in sorted(actions.items())}


def _fmt(n: int) -> str:
    return f"{n:,}"


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def write_html(candidates: dict[str, list[tuple[str, int]]], out_path: str) -> dict:
    model = build_model(candidates)
    total_reclaim = sum(g["reclaim"] for g in model)
    actions = album_actions(model)
    all_names = [g["name"] for g in model]

    # §1 album actions
    album_html = []
    for album, names in actions.items():
        chips = " ".join(
            f'<a href="{search_url(n)}" target="_blank">{html.escape(n)}</a>' for n in names
        )
        album_html.append(f"""
    <div class="grp">
      <div><b>Album: {html.escape(album)}</b> &nbsp;·&nbsp; add {len(names)} keeper(s)</div>
      <div class="chips">{chips}</div>
    </div>""")
    if not album_html:
        album_html.append('<p class="muted">No album additions needed — keepers already '
                          "cover all album memberships.</p>")

    # §2 delete batches
    batch_html = []
    for batch in _chunks(all_names, DELETE_BATCH):
        chips = " ".join(
            f'<a href="{search_url(n)}" target="_blank">{html.escape(n)}</a>' for n in batch
        )
        batch_html.append(f"""
    <div class="grp">
      <label><input type="checkbox"> batch of {len(batch)}</label>
      <div class="chips">{chips}</div>
    </div>""")

    # detail rows (sizes + per-group album info)
    detail_html = []
    for g in model:
        copies = []
        for c in g["clusters"]:
            tag, cls = ("KEEP", "keep") if c["keeper"] else ("delete", "del")
            albums = (" · albums: " + ", ".join(html.escape(a) for a in c["albums"])) \
                if c["albums"] else ""
            copies.append(f'<li class="{cls}"><b>{tag}</b> {_fmt(c["size"])} B{albums}</li>')
        detail_html.append(
            f'<div class="grp"><a href="{g["url"]}" target="_blank">"{html.escape(g["name"])}"</a>'
            f'<span class="reclaim">reclaim {_fmt(g["reclaim"])} B</span>'
            f'<ul>{"".join(copies)}</ul></div>'
        )

    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Google Photos duplicates — worklist</title>
<style>
 body {{ font:14px/1.5 system-ui,sans-serif; margin:2rem auto; max-width:920px; color:#222; }}
 h1 {{ font-size:1.3rem; }} h2 {{ font-size:1.05rem; margin-top:1.6rem; }}
 .summary {{ background:#f4f6f8; padding:.8rem 1rem; border-radius:8px; }}
 .grp {{ border-bottom:1px solid #eee; padding:.5rem 0; }}
 .chips {{ margin:.3rem 0; }}
 .chips a {{ display:inline-block; background:#eef2ff; color:#3730a3; text-decoration:none;
            padding:.1rem .45rem; margin:.12rem; border-radius:5px; font-size:.85em; }}
 .try {{ font-size:.85em; }}
 .reclaim {{ color:#999; font-size:.85em; margin-left:.5rem; }}
 ul {{ margin:.3rem 0 .3rem 1.4rem; }} li.keep {{ color:#1a7f37; }} li.del {{ color:#8a8a8a; }}
 .muted {{ color:#888; }}
 input:checked ~ * {{ opacity:.45; }}
 .note {{ color:#9a3412; background:#fff7ed; padding:.4rem .7rem; border-radius:6px; }}
</style></head><body>
<h1>Google Photos duplicate worklist</h1>
<div class="summary">
 <b>{len(model)}</b> duplicate groups &nbsp;·&nbsp; <b>{_fmt(total_reclaim)}</b> bytes reclaimable
 &nbsp;·&nbsp; <b>{len(actions)}</b> album(s) need additions.
 Keeper = smallest file (likely the storage-saver copy that doesn't consume quota; verify in UI).
</div>
<p class="note">ℹ️ Each chip is an individual filename search (the reliable way — it opens both copies of that
 photo). Combined multi-file OR search does <b>not</b> work in Google Photos (it strips underscores
 and caps terms → no results), and there is no search-by-internal-id.</p>

<h2>§1 — Add keepers to albums (do these first)</h2>
<p class="muted">Albums are grouped so you can do one album's worth in a row: for each chip, open it,
 add the keeper to this album, then move on. Re-adding a photo already in the album is harmless.</p>
{''.join(album_html)}

<h2>§2 — Delete pass (in each search, delete the LARGER copy)</h2>
{''.join(batch_html)}

<h2>Details (sizes &amp; album membership per group)</h2>
{''.join(detail_html)}
</body></html>"""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(doc)
    return {"groups": len(model), "reclaim": total_reclaim, "album_actions": len(actions)}
