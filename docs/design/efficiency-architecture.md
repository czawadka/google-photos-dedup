# Efficiency: range-read the Takeout ZIP instead of downloading 20GB

## Constraints

- User is on a **slow network**.
- The Takeout export is **~20GB**.
- There is **little spare cloud storage**, and Takeout **cannot export to S3** (only a download
  link / Drive / Dropbox / OneDrive / Box).

So moving the full 20GB across the wire is off the table.

## Architecture

A ZIP's **central directory** (all entry names + sizes + folder paths) lives at the *end* of the
file. Python's stdlib `zipfile.ZipFile`, backed by a **seekable HTTP-range file object**, reads
only that tail — yielding **every filename + size + album path** across all 20GB in
**kilobytes**.

- That alone gives same-name/different-size **candidate groups** AND **album membership**.
- **Pixels are range-fetched only for the handful of duplicate suspects** (for the SSIM /
  quality check).
- Read directly from the **Takeout download URL** (signed ~1-week link + browser cookies),
  staging nothing.

## POC-pending assumptions (biggest risks)

1. The Takeout download URL honors HTTP `Range` (returns `206`, not `200`).
2. Tail-parsing works on a real Takeout zip — watch **ZIP64** on archives >4GB; pick ≤2GB
   Takeout splits to avoid it.

**Fallbacks if Range fails:** a Drive/Dropbox-hosted copy, or chunked per-year local download.

## Producing the Takeout export (non-obvious bits)

- Takeout's Google Photos selector offers **only an album picker — no explicit date range**.
  But the album list **also includes auto-generated `Photos from <year>` buckets**, each
  containing *every* photo taken that year **including photos not in any user album**. Those year
  buckets are effectively the date-range selector.
  - **Small POC slice:** deselect all, tick a single `Photos from <Picasa-era year>` (e.g.
    2008–2012) → a full year, album + non-album, in one small zip.
  - **Full library:** select all `Photos from <year>` buckets (or leave "All photo albums
    included" fully checked).
- Choose **2 GB archive splits** to avoid ZIP64 (keeps central-directory parsing simple).
- The export is generated asynchronously and **can take hours or days**; the resulting download
  link is **signed and short-lived**, so run the range probe promptly once it's ready.

See [goal-and-keep-rule.md](goal-and-keep-rule.md) and
[google-photos-api-limitation.md](google-photos-api-limitation.md).
