# Goal and keep-rule

## Goal

Find **Picasa-era duplicate photos** in a Google Photos library: copies that share the
**same filename but differ in file size** (NOT byte-identical, so MD5/hash dedup tools miss
them — likely the same picture re-encoded at different quality). Purpose: **declutter** AND
**reclaim storage**. The tool only **recommends** deletions; the user decides.

## Keep-rule (inverted from the usual "keep biggest")

When two copies are of *similar quality*, keep the **smaller** file to save space; delete the
larger.

- **"Similar quality"** = same pixel dimensions AND perceptual-hash (pHash/dHash) distance
  below threshold AND **SSIM ≥ ~0.98**. Quality proxies: estimated JPEG quality (from
  quantization tables) + bytes-per-pixel.
- When quality **clearly differs** → **flag for manual review** (overridable to "always keep
  smaller").

### Practical refinement (learned in real use, 2026-06-11)

When deciding which copy to keep, the user also weighs Google Photos' live
**"backed up / not consuming account storage"** status (e.g. a copy that's safely backed up and
no longer counts against quota). That signal lives in the **Google Photos account UI, not in the
Takeout/Drive metadata**, so the tool **cannot** read it — this part of the decision stays a
manual check. The tool's job is to surface the candidate groups (with sizes + album membership);
the human picks the keeper.

## Album safety

A deletion candidate may belong to albums; the **kept copy must take its place** so albums
don't lose the photo. Album membership comes **only** from the Takeout **folder structure** (a
photo in an album appears in an album-named folder as well as `Photos from YYYY`) — it is **not**
in the per-photo sidecars. So detecting it requires **exporting the album folders**, which makes
Takeout duplicate the pixels (large storage cost). A year-bucket-only export has no album data.
Given the ~26 GB library, the likely decision is to **skip album auto-detection** and check album
membership in the Google Photos UI (ⓘ panel) at delete time.

## Deletion is deferred

There is no API to delete library photos, so deletion is "decide later" — manual web-UI, or
fragile browser automation explored later. The tool's job for now is to produce a reviewable
report.

### Manual deletion workflow that works (2026-06-11)

The duplicates share their **original filename** in the live library (the Takeout `(1)` suffix is
export-only). In Google Photos, **searching one filename in quotes** — e.g. `"IMG_0001.JPG"` —
returns *both* copies. The user then **adds the keeper to its album and deletes the other**.

**Report implication:** for each duplicate group, emit a one-click deep link
`https://photos.google.com/search/%22<filename>%22` (one filename per link), turning the report
into a clickable worklist.

**What does NOT work (verified):** *combined* multi-file search. Google rewrites the URL query
into an internal base64 token, **stripping underscores** (`IMG_8773`→`IMG8773`) and **dropping
terms** → "No results." So each link must be a **single** filename. A reverse-engineered base64
search-token (`gpdedup/report.py` `token_search_url`) is a candidate workaround, **pending UI
confirmation**. A nice future upgrade: read each item's sidecar `url` field to deep-link directly
to the *specific* copy to delete (disambiguates the two identical-looking results).
