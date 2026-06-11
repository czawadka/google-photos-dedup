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
  - **Workaround built, pending test:** we reverse-engineered the `/search/<base64>` protobuf
    token (`gpdedup/report.py` `search_token`/`token_search_url`); our encoder reproduces
    Google's token byte-for-byte, so a hand-built token with underscores baked in *may* survive.
    Not yet confirmed in the UI.
  - **Search by internal item id does NOT work** — filenames only.
- **Album membership — only from Takeout folder structure, NOT sidecars.** A photo in an album
  appears in an album-named folder *and* `Photos from YYYY`. Sidecars (`*.json`) carry the photo
  URL/timestamps but **no album list**. So album detection requires **exporting the album folders**
  (Takeout duplicates pixels into each → big storage hit). The user's year-bucket-only export has
  **no album data** → §1 is empty. Likely decision: **skip album auto-detection** (check albums in
  the Photos UI ⓘ panel at delete time).
- **Storage reality:** library is **~26 GB**, much of it free via legacy storage-saver; album/full
  exports run to tens of GB → a hard constraint on re-exporting.
- **Photo URL / direct links (idea, pending):** each media item's sidecar has a `url` field →
  `https://photos.google.com/photo/<id>`, a direct link to that *specific* copy. Reading sidecars
  from the existing export could give direct deep-links to the exact copy to delete (disambiguating
  identical-looking dupes) without an album re-export. **Claude cannot access these authenticated
  URLs** (sign-in wall); only a browser session can.
- **Caching:** `gpdedup/cache.py` (SQLite) stores per-part entry listings keyed by Drive
  size+modifiedTime; `poc_drive_index.py` supports `--cache/--refresh/--offline/--explain`.
  Cache persists directory listings (KB) even after the Drive export is deleted → multiple exports
  (e.g. year + albums) can be indexed sequentially and merged from cache.
- **Next:** confirm the base64 search-token workaround; decide on sidecar direct-links; promote the
  POC into a real CLI (Phase 1 in `docs/PLAN.md`).
