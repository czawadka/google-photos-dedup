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
