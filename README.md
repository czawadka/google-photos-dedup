# google-photos-dedup

Find **duplicate photos** in a Google Photos library — copies that share the **same filename but
differ in file size** *and* were **taken at the same (or near-same) time**. These are the same
picture re-encoded at a different quality, so MD5/hash dedup tools miss them (not byte-identical).
The goal is to **declutter** and **reclaim storage**.

The detection criteria is general — **same filename + different size + same/similar capture
date** — so it catches any such duplicates, not only one source. The common origin is the **Picasa
era** (Picasa re-encoded photos into different-size twins before Google Photos existed), which is
what motivated the tool, but the rule isn't Picasa-specific.

`gpdedup` reads a **Google Takeout export** sitting in Google Drive, finds same-name /
different-size candidates by range-reading only each ZIP's central directory (kilobytes, *not* the
~20 GB of pixels), **confirms** each pair by EXIF capture date — keeping only copies taken within
12 h of each other and dropping generic-name collisions like `001.JPG` taken months apart — and
writes a clickable HTML **worklist** (`delete_table.html`).

> **`gpdedup` produces a report only.** It never deletes anything and never changes albums — you
> review the report and act in the Google Photos web UI. See [why](#why-its-report-only) below.

## Why it's report-only

Three hard limits mean the last mile stays manual:

1. **No deletion / no album API.** Since **2025-03-31** the Google Photos Library API only sees
   media the calling app itself uploaded, and there has never been an API to delete a user's
   library photos. So **deleting a copy and re-adding the keeper to an album are manual** in the
   Photos web UI. (See `docs/design/google-photos-api-limitation.md`.)
2. **Album membership isn't in the data the tool reads.** A photo's album shows up only in
   Takeout's *album-folder structure*, and exporting album folders makes Takeout duplicate the
   pixels into each folder (a large storage hit); the per-photo `.json` sidecars carry **no album
   list**. A `Photos from <year>` (year-bucket) export — the practical choice — therefore has **no
   album data**, so the tool can't know or fix album membership. **You verify albums in the UI.**
   (See `docs/design/goal-and-keep-rule.md`.)
3. **Which copy to keep needs your confirmation.** The keep-rule leans toward the *smaller* file
   (save space), but the real deciding signal is Google Photos' live **"backed up / not consuming
   storage"** status — which exists **only in the account UI**, not in any Takeout/Drive metadata.
   So the report surfaces each confirmed pair (dates + sizes + direct links) and **you confirm the
   keeper**.

In short: the tool does the finding and confirming; the human does the deciding and the deleting.

## Setup

1. **Install deps** (uses [uv](https://docs.astral.sh/uv/), not pip):
   ```bash
   uv sync
   ```
2. **Produce a Takeout export** → [see below](#produce-a-takeout-export).
3. **Get a Drive token** → [see below](#get-a-drive-token).

### Produce a Takeout export

The tool has **no other data source** (the Photos API can't see your library), so a Takeout export
is required.

1. Open **Google Takeout**: <https://takeout.google.com/>.
2. Click **Deselect all**, then select only **Google Photos**.
3. Open the Google Photos detail (**All photo albums included**) and pick the **`Photos from
   <year>` buckets** for the years you want. These year buckets are the de-facto date range (the
   album picker has no date filter) and contain *every* photo from that year, album or not. Export
   whichever years you want to dedup — if you suspect Picasa-era twins, those cluster roughly in
   **2008–2014**.
4. **Next step** → delivery **Add to Drive**, frequency **Export once**, file type **.zip**, and
   size **2 GB** (2 GB splits avoid ZIP64 and keep central-directory parsing simple).
5. **Create export.** It runs asynchronously and can take hours or days. When done you'll have a
   `takeout-<timestamp>-<n>-<part>.zip` set in your Drive.

> A year-bucket export has no album membership and no "backed up" status — that's expected; both
> stay a manual UI check (see [Why it's report-only](#why-its-report-only)). Reference:
> `docs/design/efficiency-architecture.md`.

### Get a Drive token

`gpdedup` reads the archives over the Drive API with an OAuth Bearer token (`drive.readonly`):

1. Open the **OAuth Playground**: <https://developers.google.com/oauthplayground/>.
2. In *Step 1*, enter the scope `https://www.googleapis.com/auth/drive.readonly` and authorize.
3. In *Step 2*, exchange the code for tokens and copy the **access token** (`ya29...`, ~1 h expiry).
4. Export it so it stays out of your shell history:
   ```bash
   export DRIVE_TOKEN="ya29...."
   ```

## Run it

**Strongly recommended: always pass `--query` to pin the exact export.** The default query matches
*every* file named `takeout`, so if you've ever run more than one export, parts from different
exports get mixed into one index — silently producing wrong same-name groups. Scope it to a single
export by its shared name prefix (the `trashed = false` guard is added automatically):

```bash
export DRIVE_TOKEN="ya29...."
uv run gpdedup --query "name contains 'takeout-20260611T191302Z-3-'"
```

Find the right prefix from the file names in your Drive: each export's parts share a
`takeout-<timestamp>-<n>-` prefix (here `takeout-20260611T191302Z-3-`); use enough of it to match
only that export's parts. Then:

```bash
uv run gpdedup --offline       # rebuild the report from cache only (no token/network)
```

Running bare `uv run gpdedup` (no `--query`) is fine **only** if there is exactly one Takeout
export in the Drive account.

### Options

| Flag | Meaning |
| --- | --- |
| `--token` | OAuth access token (or set `DRIVE_TOKEN`). |
| `--query` | Drive `files.list` query selecting the Takeout parts. `trashed = false` is auto-added. |
| `--max-parts N` | Only read the first N parts (0 = all). Handy for a quick trial. |
| `--report PATH` | Output HTML path (default `delete_table.html`). |
| `--cache PATH` | SQLite cache of directory listings + EXIF dates. |
| `--refresh` | Re-read the central directories from Drive (ignore cached listings). |
| `--offline` | Cache only — rebuild the report with no token or network. |
| `--max-workers N` | Cap on parallel range fetches (adaptive; default 20). |
| `--no-links` | Skip per-copy deep-link resolution (sizes render unlinked). |

The cache persists directory listings **and** EXIF dates, so reruns are fast and keep working even
after you delete the Drive export.

## Use the generated report

Open `delete_table.html`. Each row is one filename with a duplicate **confirmed by capture date**
(same-name copies taken >12 h apart are different photos and are excluded). For each confirmed pair
the row shows the **capture date + each copy's size**, with the smallest tagged `keep`.

To review a row you have two links:

- **Direct media links (preferred)** — click a **linked size** to open that *exact* copy in Google
  Photos. This is essential for generic names like `001.JPG`, where a plain search returns hundreds
  of unrelated hits. (Resolved from each copy's sidecar `url`; absent only with `--no-links` or in
  offline runs.)
- **Search link (fallback)** — **open copies** opens *every* copy of that filename via Google's
  encoded `/search/<token>` form (so underscores and UUIDs survive Google's tokenizer).

The **capture date + sizes** also let you tell apart multiple real pairs that happen to share one
generic name.

### ⚠️ Before you delete: album safety

A photo you delete may belong to one or more albums, and **the tool cannot see or fix that** (see
[reason 2](#why-its-report-only)). So for each deletion:

1. Open both copies (use the direct links).
2. In the Photos UI **ⓘ info panel**, check the **albums** of the copy you're about to delete.
3. Make sure the copy you **keep** is in **all the same albums** — add it to any it's missing — so
   the album doesn't silently lose the photo.
4. Confirm the keeper using the live **"backed up / not consuming storage"** status, then delete
   the other copy.

## More

Architecture and design rationale live in [`docs/PLAN.md`](docs/PLAN.md) and
[`docs/design/`](docs/design/).
