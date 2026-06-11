"""Build a synthetic Takeout-like ZIP for the POC.

Reproduces the structure that matters for dedup:
  - ``Photos from <year>/`` folders and an album folder
  - a same-name / different-size pair (Takeout's ``(1)`` collision rename)
  - a byte-identical copy of one photo inside an album folder (= album membership)
plus several larger filler photos so the archive is multi-MB and the
"download only the tail" claim is visibly meaningful.
"""

from __future__ import annotations

import io
import os
import zipfile

from PIL import Image

HERE = os.path.dirname(__file__)
OUT = os.path.join(HERE, "fixture", "sample_takeout.zip")


def _jpeg(seed: int, size=(1600, 1200), quality: int = 88) -> bytes:
    # effect_noise gives high-entropy pixels, so the JPEG is realistically sized
    # (not a trivially-compressible solid color).
    base = Image.effect_noise(size, 48).convert("RGB")
    if seed:
        base = base.rotate(seed % 360)
    buf = io.BytesIO()
    base.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def build(force: bool = False) -> str:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if os.path.exists(OUT) and not force:
        return OUT

    # One image saved at two qualities -> same dimensions, different byte size.
    same_image_big = _jpeg(seed=0, quality=92)
    same_image_small = _jpeg(seed=0, quality=35)

    entries = [
        # the real duplicate pair: same base name, different size
        ("Takeout/Google Photos/Photos from 2015/IMG_0001.JPG", same_image_big),
        ("Takeout/Google Photos/Photos from 2015/IMG_0001(1).JPG", same_image_small),
        # byte-identical copy in an album folder = album membership signal
        ("Takeout/Google Photos/Vacation 2015/IMG_0001.JPG", same_image_big),
    ]
    # filler photos so the archive is several MB
    for i in range(2, 9):
        entries.append(
            (f"Takeout/Google Photos/Photos from 2016/IMG_{i:04d}.JPG", _jpeg(seed=i))
        )

    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_STORED) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return OUT


if __name__ == "__main__":
    path = build(force=True)
    print(f"wrote {path} ({os.path.getsize(path):,} bytes)")
