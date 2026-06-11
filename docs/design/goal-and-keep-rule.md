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

## Album safety

A deletion candidate may belong to albums; the **kept copy must take its place** so albums
don't lose the photo. Album membership comes from the Takeout entry's folder path.

## Deletion is deferred

There is no API to delete library photos, so deletion is "decide later" — manual web-UI, or
fragile browser automation explored later. The tool's job for now is to produce a reviewable
report.
