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

- **POC Part A: DONE ✓** — range-read mechanism validated locally (`poc/poc_local.py`):
  listing an 11.5MB archive's directory cost ~1KB (0.01%); single-photo extraction returned
  correct dimensions. Tests green (`uv run pytest`).
- **POC Part B: PENDING** — confirm Google's real Takeout download URL honors HTTP `Range`
  (`206`). Blocked on a Takeout export requested **2026-06-11** (Google warns it may take
  hours/days). Next action when it lands:
  `uv run python poc/poc_range_probe.py "<URL>" --header "Cookie: <...>"`, then
  `poc/poc_remote_list.py` to see real duplicates. See `poc/README.md`.
- Only after Part B passes: build the real indexer (Phase 1 in `docs/PLAN.md`).
