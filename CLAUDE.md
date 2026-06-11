# google-photos-dedup

A tool to find duplicate photos in a Google Photos library (Picasa-era duplicates that share a
**filename but differ in file size**) and recommend which copy to delete — to declutter and
reclaim storage.

## Key design facts (read these first)

- **No Google Photos API path.** Since 2025-03-31 the API only sees app-created media and can't
  delete library photos → a **Google Takeout export is the only complete source**.
  See @docs/design/google-photos-api-limitation.md
- **Goal & keep-rule.** Same-name/different-size dupes; when quality is *similar* keep the
  **smaller** file (save space), flag when quality differs; the kept copy must inherit the
  deleted copy's **album membership**. See @docs/design/goal-and-keep-rule.md
- **Efficiency / architecture.** Slow network + ~20GB export + no S3 → **range-read the Takeout
  ZIP's tail** (central directory) to get all filenames/sizes/album-paths in KB; fetch pixels
  only for duplicate suspects. A **POC is pending** to confirm the download URL honors HTTP
  `Range`. See @docs/design/efficiency-architecture.md

## Working agreements

- De-risk load-bearing assumptions with a small **POC before** a full build; report **calibrated
  confidence** with the riskiest unknowns called out; don't auto-start implementation — pause for
  approval.

## Tooling

- Use **uv** for the environment and dependencies (`uv sync`, `uv run ...`), **not** pip.

## Status (updated 2026-06-11)

- **POC Part A: DONE ✓** — range-read mechanism validated locally (`poc/poc_local.py`).
- **Direct Takeout download URL: ABANDONED** — needs Google web-session auth; cookie route
  redirects to `accounts.google.com/signin`. Don't pursue.
- **POC Part B: DONE ✓ (via Google Drive API)** — export Takeout to Drive, then range-read each
  2GB part's central directory through `files.get?alt=media` with an OAuth Bearer token (clean
  auth, honors Range → 206). `poc/poc_drive_index.py` unions all parts and lists real
  same-name/different-size duplicate candidates. Confirmed working on a real 2014 export
  (6× 2GB parts). Token from OAuth Playground (`drive.readonly`), ~1h expiry.
- **In use:** user manually reviews candidates and deletes in the Photos UI, keeping copies based
  on the live "backed up / not consuming storage" status (a signal the tool can't see — see
  goal-and-keep-rule.md).
- **Worklist report** (`gpdedup/report.py`, written by `poc_drive_index.py`): HTML with §1
  add-to-album batches and §2 delete batches, plus per-group detail.
- **Search facts (verified in the live UI — CORRECTS earlier notes):**
  - **Individual quoted filename search works** (`"IMG_6799.JPG"`) and returns *both* duplicate
    copies — this is the reliable mechanism the report uses.
  - **Combined / multi-term OR search does NOT work.** Google rewrites the URL query into an
    internal base64 token and in doing so **strips underscores** (`IMG_8773`→`IMG8773`) and
    **drops terms** (10→5, every-other), yielding **"No results."** `%5F`-encoding doesn't help.
    Don't rely on combined search.
  - **Encoded search token — CONFIRMED WORKING ✓ (user verified in UI, 2026-06-11).** We build the
    `/search/<base64>` protobuf token ourselves (`gpdedup/report.py` `search_token`/`token_search_url`,
    shape `{1: query, 4: {1: query}}`; Google adds an optional field-5 nonce we skip). Because Google
    renders our pre-built token directly instead of re-parsing plaintext, the **literal filename
    survives** — underscores AND UUIDs intact (e.g. `original_<uuid>_P` no longer collapses to
    `originalP`). **The report now always uses this token form** for search links (no more plaintext
    `%22..%22`), so there's no need to special-case "unsearchable" names.
  - **Search by internal item id does NOT work** — filenames only.
- **Album membership — only from Takeout folder structure, NOT sidecars.** A photo in an album
  appears in an album-named folder *and* `Photos from YYYY`. Sidecars (`*.json`) carry the photo
  URL/timestamps but **no album list**. So album detection requires **exporting the album folders**
  (Takeout duplicates pixels into each → big storage hit). The user's year-bucket-only export has
  **no album data** → §1 is empty. Likely decision: **skip album auto-detection** (check albums in
  the Photos UI ⓘ panel at delete time).
- **Storage reality:** library is **~26 GB**, much of it free via legacy storage-saver; album/full
  exports run to tens of GB → a hard constraint on re-exporting.
- **Sidecar direct-links (`photos.google.com/photo/<id>`) — TRIED then REMOVED (2026-06-11).** The
  idea: read each copy's sidecar `url` (a unique per-library-item id) to deep-link to the exact copy.
  Built and confirmed working (the link does open the exact photo), but **dropped — no practical
  value** for the user's workflow: the keep-decision rests on the live *"backed up / not consuming
  storage"* status, which is **UI-only** (not in Takeout metadata), so the user must open **both**
  copies in the search view to compare it anyway. A direct link to "the larger copy" doesn't match
  that decision (the keeper isn't always the smaller), and album membership is likewise UI-only — so
  the link saved no step while costing ~2× sidecar reads (one per copy). **Decision: index from the
  ZIP central directory only; report = search links.** (Claude can't open these authenticated URLs
  regardless — sign-in wall.)
- **Worklist table** (`poc/poc_report_table.py` → `gpdedup/report.py` `write_table_html`): one row
  per duplicate group — **Filename · Copies (sizes, smallest tagged 'keep') · Search (opens both
  copies)**. No sidecar/pixel reads → builds from cached central directories in well under a second.
- **Search links — encoded token form, extension dropped.** `"IMG_6799"` not `"IMG_6799.JPG"`,
  emitted as a pre-built `/search/<token>` (see encoded-search-token note above) so any filename —
  including `original_<uuid>_P` — survives Google's tokenizer. User confirmed the encoded link opens
  correctly.
- **Caching:** `gpdedup/cache.py` (SQLite) stores per-part entry listings keyed by Drive
  size+modifiedTime; `poc_drive_index.py` supports `--cache/--refresh/--offline/--explain`.
  Cache persists directory listings (KB) even after the Drive export is deleted → multiple exports
  (e.g. year + albums) can be indexed sequentially and merged from cache.
- **Videos ARE checked** (same pipeline as photos; `MEDIA_EXTENSIONS` covers `.mp4/.m4v/.mov/...`).
  The 2014 export had **271 videos / 270 distinct names → only 1 duplicate** (`MOVIE.m4v`, two
  different sizes), which the report includes. So videos are near-never duplicated: Picasa re-encoded
  *photos* into different-size twins, not videos. The current rule reports only **same-name /
  different-size** dupes, so **byte-identical** true double-uploads (the only likely video-dup form)
  are NOT caught — an optional future mode could detect them via the `(N)`-collision-sibling signal
  within one `Photos from <year>` folder (two items sharing a name = two real items, even at equal
  size).
- **FALSE POSITIVES are real & the fix is a date check (verified 2026-06-11).** Detection currently
  uses **only** normalized filename + ≥2 distinct sizes — nothing about date or content. Generic
  names (`001.JPG`…`008.JPG`, `IMG_0001`, scanner counters) collide across *different* photos →
  falsely grouped. Confirmed on real 2015 data: groups `006.JPG`/`008.JPG` had copies **68–69 days
  apart**. **Adopt rule: same-name + capture-time |Δ| ≤ 24h = legit duplicate** (24h absorbs tz/
  re-encode wobble; true clashes are months/years apart). User proposed and OK'd the 24h tolerance.
- **Date source = EXIF read from the media head, NOT zip time, NOT sidecars:**
  - **ZIP entry timestamp is useless** — Takeout writes the *export* time (all copies showed
    `2026-06-11 13:0x`, ~11y off the 2015 photos). Don't use `ZipInfo.date_time` for dating.
  - **Sidecars are sparse/inconsistent here** — a `001.JPG` group of 10 different-size copies had
    only **one** sidecar, oddly numbered (`...-metadata(8).json`). Unreliable as the date source.
  - **EXIF `DateTimeOriginal` via range-read of the first ~64 KB** of each candidate file is the
    robust answer: JPEG APP1/EXIF sits at the file head (APP1 ≤ 64 KB) and Takeout stores JPEGs
    **uncompressed**, so we range-read just the head from the zip — KB per file, no sidecar, no full
    image. `gpdedup/exif.py` (stdlib, II/MM, DateTimeOriginal→Digitized→DateTime fallback) +
    `poc/poc_exif_probe.py` (reads heads, applies ≤24h, reports bytes pulled).
    `poc/poc_date_probe.py` is the zip-vs-sidecar diagnostic that proved zip time is export time.
    Caveat: non-JPEG/stripped files (PNG, some HEIC, screenshots) lack EXIF → fall back to sidecar
    or leave date unknown and **don't** filter them out (stay safe).
- **Indexed scope now spans more years** — the cache holds many parts incl. `Photos from 2015`
  (`takeout-...-3-032.zip` etc.); 537 duplicate *candidate* groups before date-filtering (many are
  false positives the date rule will drop). Cache merges across exports as added.
- **Next:** wire `same-name + Δ≤24h` (EXIF head-read date, sidecar fallback) into `group_candidates`
  as the real dedup criterion; then re-measure the true duplicate count. Later: byte-identical dup
  detection (videos/double-uploads); promote POC → CLI (Phase 1 in `docs/PLAN.md`).
