"""POC part B — probe whether a real URL honors HTTP Range requests.

Point this at your actual Takeout download URL (signed link from takeout.google.com,
or a Drive/Dropbox direct link). It sends a tiny suffix-range request and reports
whether the server answers with 206 Partial Content. If it does, the whole
range-read approach works against your real export; if it returns 200, we fall
back to a Drive/Dropbox copy or chunked download.

Usage:
    uv run python poc/poc_range_probe.py "<URL>"
    uv run python poc/poc_range_probe.py "<URL>" --header "Cookie: SID=...; HSID=..."

Tip: grab the URL + cookies from your browser's DevTools (Network tab) while the
Takeout download is starting, or use the "Copy as cURL" option.
"""

from __future__ import annotations

import argparse
import urllib.request


def probe(url: str, headers: dict, suffix: int = 65536) -> int:
    print(f"Probing: {url[:90]}{'...' if len(url) > 90 else ''}\n")
    attempts = [("suffix", f"bytes=-{suffix}"), ("prefix", "bytes=0-0")]
    supported = False
    for label, rng in attempts:
        req = urllib.request.Request(url, headers={**headers, "Range": rng})
        try:
            with urllib.request.urlopen(req) as resp:
                status = getattr(resp, "status", resp.getcode())
                cr = resp.headers.get("Content-Range")
                cl = resp.headers.get("Content-Length")
                ar = resp.headers.get("Accept-Ranges")
                print(f"[{label}] Range: {rng}")
                print(f"    status         : {status}")
                print(f"    Content-Range  : {cr}")
                print(f"    Content-Length : {cl}")
                print(f"    Accept-Ranges  : {ar}")
                if status == 206:
                    supported = True
                    print("    -> 206 Partial Content (range honored) ✓\n")
                else:
                    print("    -> NOT 206 (range likely ignored) ✗\n")
        except urllib.error.HTTPError as exc:
            print(f"[{label}] Range: {rng} -> HTTP {exc.code} {exc.reason}\n")
        except Exception as exc:  # noqa: BLE001
            print(f"[{label}] Range: {rng} -> error: {exc}\n")

    if supported:
        print("RESULT: range-read IS supported for this URL ✓")
        return 0
    print("RESULT: range-read is NOT supported for this URL ✗ (use a fallback)")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("url")
    ap.add_argument(
        "--header", action="append", default=[],
        help='extra request header, e.g. --header "Cookie: SID=..."',
    )
    ap.add_argument("--suffix", type=int, default=65536)
    args = ap.parse_args()

    headers = {}
    for h in args.header:
        name, _, value = h.partition(":")
        headers[name.strip()] = value.strip()
    return probe(args.url, headers, args.suffix)


if __name__ == "__main__":
    raise SystemExit(main())
