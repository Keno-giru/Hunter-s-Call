#!/usr/bin/env python3
"""Serve the hub folder locally, with HTTP Range support so the video player can seek.

    python tools/serve.py            # http://localhost:8000/   (library: /datasets/index.html)
    python tools/serve.py --port 8080 --dir "Galileo Tactical Hub"

Listens on 127.0.0.1 only: nothing is exposed to your network unless you pass --host.
"""

import argparse
import json
import mimetypes
import os
import re
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("video/webm", ".webm")
mimetypes.add_type("application/json", ".json")
mimetypes.add_type("text/javascript", ".js")


MATCH_INFO_KEYS = {"home", "away", "competition", "date", "venue", "clock", "score_start", "goals", "score_final", "notes"}


def update_catalog(root, match_dir, info):
    """Put the saved match info into datasets/catalog.json, so the hub's match picker shows it at once."""
    cat_path = root / "datasets" / "catalog.json"
    try:
        cat = json.loads(cat_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    rel = match_dir.relative_to(root / "datasets").as_posix()
    for m in cat.get("matches", []):
        if m.get("dir") == rel:
            m["info"] = info
    cat_path.write_text(json.dumps(cat, indent=1, ensure_ascii=False), encoding="utf-8")


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

    # ---- local endpoints: match info (the one write), sandbox (read-only computation)
    def do_POST(self):
        route = self.path.split("?")[0]
        if route == "/api/sandbox":
            return self._sandbox()
        if route != "/api/match-info":
            return self.send_error(404)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if not 0 < n <= 64 * 1024:
                return self._json(413, {"error": "body must be 1 byte to 64 KB"})
            body = json.loads(self.rfile.read(n).decode("utf-8"))
            pack, info = body.get("pack"), body.get("info")
            if not isinstance(pack, str) or not isinstance(info, dict):
                return self._json(400, {"error": "need {pack: <relative path to pack.ghp.json>, info: {...}}"})
            root = Path(self.directory).resolve()
            target = (root / pack).resolve()
            matches = (root / "datasets" / "matches").resolve()
            if target.name != "pack.ghp.json" or not target.is_file() or matches not in target.parents:
                return self._json(403, {"error": "pack must be a pack.ghp.json under datasets/matches"})
            info = {k: v for k, v in info.items() if k in MATCH_INFO_KEYS}
            out = target.parent / "match_info.json"
            out.write_text(json.dumps(info, indent=1, ensure_ascii=False), encoding="utf-8")
            update_catalog(root, target.parent, info)
            return self._json(200, {"ok": True, "file": out.relative_to(root).as_posix()})
        except (ValueError, UnicodeDecodeError) as e:
            return self._json(400, {"error": f"bad JSON: {e}"})

    def _sandbox(self):
        """POST {state, option?} -> {state, analysis}. option given: play it first (step), then analyse the new moment.
        Computes only; writes nothing. Needs numpy (run the server with the project's Python)."""
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if not 0 < n <= 512 * 1024:
                return self._json(413, {"error": "body must be 1 byte to 512 KB"})
            body = json.loads(self.rfile.read(n).decode("utf-8"))
            state = body.get("state")
            if not isinstance(state, dict) or not isinstance(state.get("players"), list) or len(state["players"]) > 60:
                return self._json(400, {"error": "need {state: {players: [...] (max 60), carrier: index}}"})
            pack = state.get("pack")
            root = Path(self.directory).resolve()
            if pack is not None:
                tgt = (root / str(pack)).resolve()
                if not isinstance(pack, str) or (root / "datasets") not in tgt.parents or not tgt.is_file():
                    state["pack"] = None
            try:
                sys.path.insert(0, str(Path(__file__).resolve().parent))
                from galileo_data import sandbox as SB
            except ImportError as e:
                return self._json(503, {"error": f"sandbox needs numpy in the server's Python ({e})"})
            opt, c = body.get("option"), body.get("call")
            ended = None
            if isinstance(opt, dict):
                state = SB.step(state, opt, root)
                ended = state.pop("ended", None)
            elif isinstance(c, dict):
                state = SB.call(state, c, root)
            analysis = None if ended else SB.analyse(state, root)
            return self._json(200, {"state": state, "analysis": analysis, "ended": ended})
        except (ValueError, KeyError, TypeError, UnicodeDecodeError) as e:
            return self._json(400, {"error": f"{type(e).__name__}: {e}"})
        except RuntimeError as e:
            return self._json(409, {"error": str(e)})

    def _json(self, code, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

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
