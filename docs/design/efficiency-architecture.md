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

See [goal-and-keep-rule.md](goal-and-keep-rule.md) and
[google-photos-api-limitation.md](google-photos-api-limitation.md).
