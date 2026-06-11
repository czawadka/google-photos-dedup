"""Minimal HTTP server that honors Range requests (including suffix ranges).

Used to validate HttpRangeReader locally, and to document exactly what a remote
host (e.g. the Takeout download URL) must support for the range-read approach to
work: respond to ``Range: bytes=...`` with ``206 Partial Content`` and a correct
``Content-Range`` header.
"""

from __future__ import annotations

import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def _make_handler(directory: str):
    class RangeHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the POC output clean
            pass

        def _resolve(self):
            path = self.path.split("?", 1)[0].lstrip("/")
            full = os.path.join(directory, path)
            return full if os.path.isfile(full) else None

        def do_HEAD(self):
            self._serve(head_only=True)

        def do_GET(self):
            self._serve(head_only=False)

        def _serve(self, head_only: bool):
            full = self._resolve()
            if not full:
                self.send_error(404)
                return
            size = os.path.getsize(full)
            rng = self.headers.get("Range")
            if not rng:
                self.send_response(200)
                self.send_header("Content-Length", str(size))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                if not head_only:
                    with open(full, "rb") as f:
                        self.wfile.write(f.read())
                return

            m = _RANGE_RE.fullmatch(rng.strip())
            if not m:
                self.send_error(416)
                return
            s, e = m.group(1), m.group(2)
            if s == "":  # suffix range: bytes=-N
                length = min(int(e), size)
                start, end = size - length, size - 1
            else:
                start = int(s)
                end = min(int(e), size - 1) if e else size - 1
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            length = end - start + 1
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            if not head_only:
                with open(full, "rb") as f:
                    f.seek(start)
                    self.wfile.write(f.read(length))

    return RangeHandler


def serve_directory(directory: str, port: int = 0):
    """Start a background Range-capable server; return (httpd, base_url)."""
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _make_handler(directory))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    _, bound_port = httpd.server_address
    return httpd, f"http://127.0.0.1:{bound_port}"
