"""POC part A — local end-to-end validation of the range-read approach.

Builds a synthetic Takeout-like ZIP, serves it over a Range-capable local HTTP
server, then uses HttpRangeReader + stdlib zipfile to:
  1. list every entry (name + size + album path) reading ONLY the archive tail,
  2. extract a single photo and read its real JPEG dimensions,
all while counting the bytes actually downloaded.

Success = the listing costs a tiny fraction of the archive size, and the
extracted entry is a valid image of the expected dimensions.
"""

from __future__ import annotations

import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gpdedup.http_range import HttpRangeReader  # noqa: E402
from gpdedup.jpeg import read_jpeg_dimensions  # noqa: E402
from poc import make_fixture  # noqa: E402
from poc.range_server import serve_directory  # noqa: E402

TARGET = "Takeout/Google Photos/Photos from 2015/IMG_0001.JPG"
EXPECTED_DIMS = (1600, 1200)


def main() -> int:
    zip_path = make_fixture.build()
    total = os.path.getsize(zip_path)
    httpd, base_url = serve_directory(os.path.dirname(zip_path))
    try:
        url = f"{base_url}/{os.path.basename(zip_path)}"
        reader = HttpRangeReader(url)

        # 1) List the central directory (tail-only read).
        with zipfile.ZipFile(reader) as zf:
            infos = zf.infolist()
            list_bytes = reader.bytes_downloaded
            list_reqs = reader.request_count

            print(f"\nArchive: {url}")
            print(f"Total archive size: {total:,} bytes\n")
            print(f"{'entry':<58}{'size':>10}")
            print("-" * 68)
            for info in infos:
                print(f"{info.filename:<58}{info.file_size:>10,}")

            # 2) Extract one entry and read its real dimensions.
            before = reader.bytes_downloaded
            data = zf.read(TARGET)
            extract_bytes = reader.bytes_downloaded - before
            w, h = read_jpeg_dimensions(data)

        print("\n--- efficiency ---")
        print(f"list directory ({len(infos)} entries): "
              f"{list_bytes:,} bytes in {list_reqs} requests "
              f"= {list_bytes / total:.2%} of the archive")
        print(f"extract 1 photo ({TARGET.split('/')[-1]}): "
              f"{extract_bytes:,} bytes -> dimensions {w}x{h}")
        print(f"total downloaded: {reader.bytes_downloaded:,} / {total:,} bytes\n")

        ok = True
        if (w, h) != EXPECTED_DIMS:
            print(f"FAIL: dimensions {w}x{h} != expected {EXPECTED_DIMS}")
            ok = False
        if list_bytes >= total:
            print("FAIL: listing downloaded the whole archive")
            ok = False
        names = {i.filename for i in infos}
        if not {TARGET, "Takeout/Google Photos/Photos from 2015/IMG_0001(1).JPG"} <= names:
            print("FAIL: expected duplicate pair not found in listing")
            ok = False

        print("POC LOCAL: PASS ✓" if ok else "POC LOCAL: FAIL ✗")
        return 0 if ok else 1
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
