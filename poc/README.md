# Range-read POC

Proves we can find duplicates in a ~20GB Takeout export **without downloading it**,
by reading only the ZIP's central directory (its tail) over HTTP Range requests.

## Part A — local, self-contained (no real data needed)

```bash
uv run python poc/poc_local.py
```

Builds a synthetic Takeout-like ZIP (a same-name/different-size duplicate pair, a
byte-identical album copy, plus filler photos), serves it over a Range-capable
local server, then lists every entry and extracts one photo — reporting how few
bytes were actually downloaded. Validates the whole mechanism end to end.

## Part B — against your real Takeout URL

1. Start a Takeout export of **Google Photos** (a small slice is fine — one album
   or one year). Choose **2 GB** archive splits to avoid ZIP64.
2. When the download starts, grab the **URL** (and `Cookie` header if present)
   from your browser DevTools → Network tab ("Copy as cURL" works).
3. Check the server honors ranges:

   ```bash
   uv run python poc/poc_range_probe.py "<URL>" --header "Cookie: <...>"
   ```

   Want a `206 Partial Content`. A `200` means ranges are ignored → use a
   Drive/Dropbox copy or chunked download instead.
4. If supported, list the real archive cheaply:

   ```bash
   uv run python poc/poc_remote_list.py "<URL>" --header "Cookie: <...>"
   ```

   You should see your real filenames/sizes — including the same-name,
   different-size Picasa duplicates — for a few KB of transfer.
