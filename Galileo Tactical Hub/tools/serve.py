#!/usr/bin/env python3
"""Serve the hub folder locally, with HTTP Range support so the video player can seek.

    python tools/serve.py            # http://localhost:8000/   (library: /datasets/index.html)
    python tools/serve.py --port 8080 --dir "Galileo Tactical Hub"

Listens on 127.0.0.1 only: nothing is exposed to your network unless you pass --host.
"""

import argparse
import mimetypes
import os
import re
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("video/webm", ".webm")
mimetypes.add_type("application/json", ".json")
mimetypes.add_type("text/javascript", ".js")


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if args and str(args[1])[:1] in "45":
            super().log_message(fmt, *args)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def send_head(self):
        path = self.translate_path(self.path)
        m = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range", "").strip())
        if not m or not os.path.isfile(path) or (not m.group(1) and not m.group(2)):
            self._remaining = None
            return super().send_head()
        size = os.path.getsize(path)
        if m.group(1):
            a = int(m.group(1))
            b = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
        else:
            a, b = max(0, size - int(m.group(2))), size - 1
        if a >= size or a > b:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return None
        f = open(path, "rb")
        f.seek(a)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {a}-{b}/{size}")
        self.send_header("Content-Length", str(b - a + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self._remaining = b - a + 1
        return f

    def copyfile(self, src, dst):
        n = getattr(self, "_remaining", None)
        if n is None:
            return super().copyfile(src, dst)
        try:
            while n > 0:
                chunk = src.read(min(1 << 16, n))
                if not chunk:
                    break
                dst.write(chunk)
                n -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass                                  # the player cancelled a range request: normal while seeking
        self._remaining = None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), partial(Handler, directory=a.dir))
    print(f"serving {a.dir}\n  hub:     http://localhost:{a.port}/index.html\n  library: http://localhost:{a.port}/datasets/index.html")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
