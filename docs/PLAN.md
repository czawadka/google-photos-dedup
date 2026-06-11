# Google Photos Duplicate Finder — Plan

## Context

The user's Google Photos library contains duplicate pictures created during the Picasa era
(before Google Photos existed). The duplicates share the **same filename but differ in file
size** — meaning they are **not byte-identical**, so ordinary MD5/hash dedup tools miss them.
They are most likely the same picture re-encoded at a different quality/resolution.

Goals:
1. **Declutter** the library by finding these duplicate groups.
2. **Reclaim storage** — when two copies are of *similar quality*, propose keeping the **smaller**
   file and deleting the larger (inverted from the usual "keep biggest").
3. **Never silently lose data** — a deletion candidate may belong to one or more **albums**; the
   kept copy must take its place so albums don't lose the photo.

### Constraints that drive the architecture
- **No API path.** Since **March 31, 2025** the Google Photos Library API only sees app-created
  media (`photoslibrary.readonly` etc. removed → `403`). `mediaItems.list` returns only our own
  uploads; the Picker API can't enumerate the library; there has never been a delete API. So the
  **only complete source is a Google Takeout export**.
- **Slow network + ~20GB export = the real bottleneck.** We must avoid moving 20GB. The 20GB is
  almost all pixels we don't need; what we need first is just *filename + size + album path* for
  every file, which is tiny.
- **No spare cloud storage / no S3.** Takeout can only export to a download link, Drive, Dropbox,
  OneDrive, or Box — **not S3**. Staging 20GB anywhere is off the table.
- **Deletion deferred** ("decide later"): the tool produces a *reviewable report*; the user deletes
  manually in the Photos web UI, with optional browser automation later.

### Chosen approach: range-read the Takeout archive in place
A ZIP's central directory (the list of all entries + their sizes + paths) sits at the **end** of
the file. Python's stdlib `zipfile.ZipFile` reads only that tail to enumerate entries, and seeks
to individual entries on `.open()`. By backing it with a **seekable HTTP-range file object**, we:
- get **every filename + size + album-folder path** across all 20GB by transferring only a few KB
  (this alone yields the same-name/different-size candidate groups **and** album membership);
- range-fetch **actual pixels only for the handful of duplicate suspects** (for the quality check).

The archive is range-read **directly from the Takeout download URL** (signed, ~1-week link; needs
the browser's auth cookies), staging nothing locally or in the cloud. Drive/Dropbox-hosted copies
are a fallback if the download URL doesn't honor ranges.

### Decisions captured
- **Stack:** Python (stdlib `zipfile` for the trick; Pillow/imagehash/numpy/scikit-image for
  quality; `requests`/`urllib` for range reads). No other preference.
- **Keep rule:** *similar quality → keep the smaller file*; quality clearly differs → **flag for
  manual review** (overridable to "always keep smaller").
- **"Similar quality"** = same dimensions AND perceptual-hash (pHash/dHash) distance below
  threshold AND **SSIM ≥ ~0.98**; quality proxies = estimated JPEG quality (quantization tables)
  + bytes-per-pixel.
- **Albums:** captured from the entry path inside the zip (e.g.
  `Takeout/Google Photos/<Album>/IMG.jpg`) — free during the directory read.

## Phase 0 — Proof of Concept (FIRST deliverable; de-risks the whole approach)

Prove the two load-bearing assumptions before building anything else:
- **A. ZIP-tail parsing** on a small, locally-downloaded Takeout `.zip`: using a byte counter,
  list every entry (name + size + album path) reading **only the tail** (not the whole file);
  then extract a single entry by name and read its JPEG dimensions. Proves real Takeout zip
  structure parses and that targeted single-photo extraction works.
- **B. Remote range support**: issue a suffix-range request (`Range: bytes=-65536`) to the real
  Takeout download URL (with the user's cookies) and confirm **HTTP 206 Partial Content** + that
  `Content-Range` is honored. If the server returns `200` (full body), range-read is unavailable
  → fall back to Drive/Dropbox copy or local incremental download.

**Success criterion:** produce a filename+size+album listing of a real Takeout archive while the
bytes-downloaded counter shows only kilobytes, and fetch one photo's pixels by range.

**POC asks of the user:** do one **small** Takeout export (a single album or year) to get (1) a
local `.zip` for part A and (2) a live download URL + cookies for part B.

## Implementation phases (after POC)

1. **Remote index + candidate report** (the user's "find samples first" ask): walk all archives'
   central directories via the range reader → build a SQLite index of every entry
   (normalized base name — strip Takeout `IMG_1234(1).JPG` suffixes — size, album path). Group by
   normalized name; split **byte-identical copies** (album-membership signal, *not* dupes) from
   **different-size copies** (real candidates). Emit a report of candidate groups with size /
   date / album memberships so the user can *see* their duplicates. Metadata-only, no pixel
   downloads.
2. **Quality comparison + recommendation:** range-fetch pixels for candidate groups only; compute
   pHash/dHash, SSIM, estimated JPEG quality. Apply keep-smallest-when-similar /
   flag-when-quality-differs. Richer HTML report with side-by-side stats + thumbnails, plus a
   CSV/JSON deletion-candidate list. Each candidate annotated with its albums + the replacement
   copy that must inherit them.
3. **Deletion (deferred / decide later):** start with the manual report; optionally add a
   Playwright-assisted "select & delete in photos.google.com" step that also re-adds the kept copy
   to the affected albums. Fragile and outside Google's ToS — revisit only if manual is too
   tedious.

## Proposed structure

```
google-photos-dedup/
  pyproject.toml            # deps: requests, Pillow, imagehash, numpy, scikit-image
  README.md                 # how to run a (small) Takeout export + the tool; how to grab URL+cookies
  gpdedup/
    http_range.py           # seekable file-like over HTTP range requests (+ bytes-downloaded counter)
    zip_index.py            # ZipFile(reader) → entries (name, size, album path); single-entry extract
    cache.py                # SQLite index of entries
    grouping.py             # name normalization; byte-identical vs different-size split
    quality.py              # pHash/dHash, SSIM, JPEG-quality estimate (range-fetched pixels)
    recommend.py            # keep-smallest-when-similar / flag-when-differs
    report.py               # HTML (thumbnails + side-by-side stats) + CSV/JSON export
    cli.py                  # subcommands: poc, index, report
  poc/
    poc_zip_tail.py         # Phase 0 part A (local zip)
    poc_range_probe.py      # Phase 0 part B (remote 206 check)
  tests/
    test_grouping.py        # (1)-suffix normalization; byte-identical vs dupe classification
    test_recommend.py       # similar → keep smallest; differing dims → flagged
    test_zip_index.py       # tail-only parse + single-entry extract on a fixture zip
```

## Verification

- **POC (gates everything):** run `poc_zip_tail.py` on a real small Takeout zip — confirm the
  byte counter stays in the KB range while listing all entries, and that one extracted photo's
  dimensions read correctly; run `poc_range_probe.py` against the live URL — confirm `206`.
- **Unit tests:** name normalization + byte-identical-vs-dupe classification (`test_grouping.py`);
  keep-rule for similar vs differing quality (`test_recommend.py`); tail-only enumeration + single
  entry extraction on a synthetic fixture zip (`test_zip_index.py`).
- **Synthetic quality fixture:** one base image saved at two JPEG qualities (same dims, different
  size) + one downscaled copy → first pair recommends "keep smaller", downscaled → "review".
- **End-to-end on a real (small) export:** `gpdedup index <url>` then `gpdedup report` and eyeball
  the candidate groups against known duplicates before any deletion is ever performed.
