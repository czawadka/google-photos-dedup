# AGENTS.md

Guidance for any coding agent working in this repo. (Claude Code reads `CLAUDE.md`, which points
here.)

## What this is

`gpdedup` finds **duplicate photos** in a Google Photos library — copies that share the **same
filename but differ in file size** *and* were **taken at the same (or near-same) time**. These are
the same picture re-encoded at a different quality, so MD5/hash dedup tools miss them (not
byte-identical). The common origin is the **Picasa era**, but the rule isn't Picasa-specific.

It reads a **Google Takeout export sitting in Google Drive**, finds same-name/different-size
candidates by range-reading only each ZIP's central directory (kilobytes, *not* the ~20 GB of
pixels), **confirms** each pair by EXIF capture date, and writes a clickable HTML worklist
(`delete_table.html`).

> **`gpdedup` is report-only.** It never deletes anything and never changes albums. The human
> reviews the report and acts in the Google Photos web UI. See the constraints below for why the
> last mile must stay manual.

## Hard constraints (read these first)

- **No Google Photos API path.** Since 2025-03-31 the API only sees app-created media and can't
  delete library photos → a Google Takeout export is the only complete source.
  See [docs/design/google-photos-api-limitation.md](docs/design/google-photos-api-limitation.md).
- **Goal & keep-rule.** Same-name/different-size dupes; when quality is *similar* keep the
  **smaller** file (save space), flag when quality differs. The real keep signal — Google Photos'
  live "backed up / not consuming storage" status — is **UI-only**, not in Takeout metadata, so the
  tool surfaces candidates and the human decides. Album membership is likewise UI-only.
  See [docs/design/goal-and-keep-rule.md](docs/design/goal-and-keep-rule.md).
- **Efficiency / architecture.** Slow network + ~20 GB export + no S3 → range-read the Takeout
  ZIP's tail (central directory) to get all filenames/sizes/album-paths in KB; fetch pixels only
  for duplicate suspects. See [docs/design/efficiency-architecture.md](docs/design/efficiency-architecture.md).

## Commands

Use **uv** for the environment and dependencies (`uv sync`, `uv run ...`), **not** pip.

```bash
uv sync                                            # install deps
uv run pytest                                      # run the test suite (tests/)
uv run gpdedup --query "name contains 'takeout-...-'"   # run it (needs DRIVE_TOKEN; pin the export)
uv run gpdedup --offline                           # rebuild the report from cache, no token/network
uv run python poc/poc_local.py                     # self-contained POC, no real data needed
```

`gpdedup` needs an OAuth Bearer token (`drive.readonly`) in `DRIVE_TOKEN`. **Always pass `--query`**
to pin one export — the default matches *every* file named `takeout`, so parts from different
exports get mixed and produce wrong groups. Full setup (Takeout export, token) is in
[README.md](README.md).

## Repo map

| Path | What |
| --- | --- |
| `gpdedup/` | The package. `cli.py` (entrypoint), `central_dir.py` + `http_range.py` + `drive*.py` (range-read ZIP central dirs over the Drive API), `dating.py` + `exif.py` (EXIF capture-date confirmation), `grouping.py` (candidate grouping + false-positive filters), `sidecar.py` (per-copy deep links), `report.py` (HTML worklist), `cache.py` (SQLite cache), `concurrency.py` (adaptive parallel fetch). |
| `poc/` | Exploratory scripts kept for reference (range-read POC, probes). Not part of the shipped CLI. |
| `tests/` | pytest suite, roughly one file per `gpdedup` module. |
| `docs/` | `PLAN.md` + `design/` (the rationale docs linked above). |

## Working agreements

- De-risk load-bearing assumptions with a small **POC before** a full build.
- Report **calibrated confidence** with the riskiest unknowns called out.
- Don't auto-start implementation — pause for approval.

## Gotchas / invariants

- **Detection rule** = normalized filename + ≥2 distinct sizes, **confirmed by EXIF capture date**
  within 12 h. The date check drops generic-name collisions (`001.JPG`, scanner counters) where
  unrelated photos share a name but were taken months apart. Clustering is **pairwise**, not
  group-wide — a generic-name group can hold both real pairs and unrelated singletons.
- **Date source = EXIF read from the file head, NOT the ZIP entry timestamp** (Takeout writes the
  *export* time, ~years off) and **NOT sidecars** (sparse/inconsistent). `gpdedup/exif.py` reads
  `DateTimeOriginal` from the first ~64 KB.
- **Takeout entries are DEFLATE-compressed.** Head reads fetch compressed bytes and raw-inflate the
  first ~64 KB (`gpdedup/drive_fetch.py`).
- **Search links use the pre-built encoded `/search/<token>` form** so underscores/UUIDs survive
  Google's tokenizer. Don't switch back to plaintext `%22..%22` search URLs.
- **Takeout caps basenames at 51 chars** → `original_<uuid>_*` renditions collapse to one name and
  form a false-positive class with identical EXIF instants. They're excluded via
  `gpdedup/grouping.py` `is_truncated_name` — not deletable library duplicates.
- **Cache** (`gpdedup/cache.py`, SQLite) persists directory listings, entry offsets, and EXIF dates,
  so reruns and `--offline` work even after the Drive export is deleted. Fetches are parallel, but
  **SQLite access stays on the main thread**.
