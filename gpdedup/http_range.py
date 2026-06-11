"""A seekable, read-only file-like object backed by HTTP Range requests.

This is the core of the range-read approach: it lets the stdlib ``zipfile``
module read a *remote* ZIP's central directory (which lives at the tail of the
file) and extract individual entries, while downloading only the bytes that are
actually touched. For a ~20GB Takeout archive, listing every entry's
name+size+path costs only kilobytes.

Instrumentation (``bytes_downloaded`` / ``request_count``) makes the efficiency
claim measurable, and a non-206 response is turned into a clear error so the POC
can detect a server that does not honor ranges.
"""

from __future__ import annotations

import io
import urllib.request


class RangeNotSupported(OSError):
    """Raised when the server answers a Range request with a full 200 body."""


class HttpRangeReader(io.RawIOBase):
    def __init__(self, url: str, headers: dict | None = None):
        self.url = url
        self._headers = dict(headers or {})
        self._pos = 0
        self._size: int | None = None
        self.bytes_downloaded = 0
        self.request_count = 0

    # --- size discovery -------------------------------------------------
    @property
    def size(self) -> int:
        if self._size is None:
            self._size = self._discover_size()
        return self._size

    def _discover_size(self) -> int:
        # A 0-0 range avoids a HEAD (some signed URLs reject HEAD) and returns
        # the full length via the Content-Range header: "bytes 0-0/<total>".
        req = urllib.request.Request(
            self.url, headers={**self._headers, "Range": "bytes=0-0"}
        )
        with urllib.request.urlopen(req) as resp:
            self.request_count += 1
            status = getattr(resp, "status", resp.getcode())
            content_range = resp.headers.get("Content-Range")
            if status == 206 and content_range and "/" in content_range:
                total = content_range.rsplit("/", 1)[1]
                if total != "*":
                    return int(total)
            content_length = resp.headers.get("Content-Length")
            if content_length is not None:
                return int(content_length)
        raise OSError("Could not determine remote size (no Content-Range/Length)")

    # --- io.RawIOBase interface ----------------------------------------
    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            self._pos = offset
        elif whence == io.SEEK_CUR:
            self._pos += offset
        elif whence == io.SEEK_END:
            self._pos = self.size + offset
        else:
            raise ValueError(f"invalid whence: {whence}")
        return self._pos

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            return self.readall()
        if n == 0:
            return b""
        size = self.size
        if self._pos >= size:
            return b""
        end = min(self._pos + n - 1, size - 1)
        data = self._fetch(self._pos, end)
        self._pos += len(data)
        return data

    def readall(self) -> bytes:
        return self.read(self.size - self._pos)

    def readinto(self, b) -> int:
        data = self.read(len(b))
        b[: len(data)] = data
        return len(data)

    # --- the one network primitive -------------------------------------
    def _fetch(self, start: int, end: int) -> bytes:
        req = urllib.request.Request(
            self.url, headers={**self._headers, "Range": f"bytes={start}-{end}"}
        )
        with urllib.request.urlopen(req) as resp:
            self.request_count += 1
            status = getattr(resp, "status", resp.getcode())
            if status != 206:
                raise RangeNotSupported(
                    f"server returned {status} (not 206) for a Range request; "
                    "the range-read approach is unavailable for this URL"
                )
            data = resp.read()
        self.bytes_downloaded += len(data)
        return data
