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
- **Photo URL / direct links — BUILT ✓ & CONFIRMED working (user verified the link opens the exact
  photo, 2026-06-11).** Each media item's sidecar `url` field (`https://photos.google.com/photo/<id>`)
  is a **unique per-library-item id**: the two duplicate copies are *different* library items, so
  their sidecars carry *different* urls → a direct link disambiguates the otherwise identical-looking
  search results. **Claude cannot open these authenticated URLs** (sign-in wall); only the user's
  browser can.
  - **Delete table** (`poc/poc_report_table.py` → `gpdedup/report.py` `write_table_html`): one row
    per to-delete copy, columns **Filename · Keep (smaller, direct link) · Delete (larger, direct
    link) · Search (fallback)**. With both direct links the workflow needs **no search**: open
    *delete* → read its albums in the ⓘ panel & remove it; open *keep* → add it to those albums.
  - **Getting ids for all copies costs 2× the pairs** (~196 sidecar reads for 98 photo pairs); the
    delete-only column needs just the larger copy (~98). Each sidecar JSON is ~1–2 KB by range, so
    cheap. Sidecar urls are cached (SQLite `sidecars` table) → reruns/`--offline` don't re-fetch.
  - **Uniqueness assertion:** the tool checks `keep_url != delete_url` per group and flags any
    clash (⚠) — so the "ids distinguish the copies" claim is verified against real data, not assumed.
  - **Sidecar↔media matching** (`gpdedup/sidecar.py`): a **reverse-index** approach — read the real
    `*.json` entries and map each back to the media file it describes, stripping *any* metadata
    suffix and tolerating the `(N)` collision marker on either the media stem *or* the sidecar tail.
    Far more robust than guessing names (the first guesser matched only ~42 of ~98). `--diagnose N`
    prints unmatched copies + the `.json` siblings in their folder to debug stragglers.
  - **Search links: extension dropped + encoded token form.** `"IMG_6799"` not `"IMG_6799.JPG"`,
    emitted as a pre-built `/search/<token>` (see encoded-search-token note above) so any filename —
    including `original_<uuid>_P` — survives Google's tokenizer. User confirmed the encoded link
    opens correctly.
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
- **Indexed scope so far = 2014 only** (the 6 cached parts `takeout-...-3-00{1..6}.zip` are all
  `Photos from 2014`). Other years aren't indexed yet; the cache merges across exports as added.
- **Next:** decide on byte-identical dup detection (videos/double-uploads); index other years;
  optionally confirm the base64 search-token workaround; promote the POC into a real CLI (Phase 1
  in `docs/PLAN.md`).
