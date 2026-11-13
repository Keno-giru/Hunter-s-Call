# End-to-end exam for footage calibration over time, the overlay warp and drawing on video.
# Generates a synthetic broadcast clip with exact ground truth (gen_clip.py), serves the hub with HTTP
# Range support (media seeking needs it), drives real Chrome through Playwright, and gates the result.
#
#   python3 tests/e2e/run_e2e.py [--chrome /path/to/chrome] [--keep]
#
# Needs: pip install playwright numpy opencv-python; ffmpeg on PATH; a Chrome/Chromium
# (Playwright's own: `playwright install chromium`, or pass --chrome). Exit code 0 = every gate passed.
import argparse, json, math, os, random, re, shutil, subprocess, sys, threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
HUB = os.path.abspath(os.path.join(HERE, "..", ".."))
ap = argparse.ArgumentParser()
ap.add_argument("--chrome", default=os.environ.get("CHROME") or None)
ap.add_argument("--keep", action="store_true", help="keep screenshots in tests/e2e/out")
args = ap.parse_args()

OUT = os.path.join(HERE, "out")
if not os.path.exists(os.path.join(OUT, "gt.json")):
    subprocess.check_call([sys.executable, os.path.join(HERE, "gen_clip.py"), OUT])
GT = json.load(open(os.path.join(OUT, "gt.json")))
CLIP = "_e2e_test_pan.webm"
shutil.copy(os.path.join(OUT, "test_pan.webm"), os.path.join(HUB, "data", CLIP))

class Range(SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
    def send_head(self):
        path = self.translate_path(self.path)
        m = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range", ""))
        if not m or not os.path.isfile(path): return super().send_head()
        size = os.path.getsize(path)
        a = int(m.group(1)) if m.group(1) else max(0, size - int(m.group(2)))
        b = min(int(m.group(2)) if m.group(1) and m.group(2) else size - 1, size - 1)
        f = open(path, "rb"); f.seek(a)
        self.send_response(206); self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {a}-{b}/{size}"); self.send_header("Content-Length", str(b - a + 1))
        self.send_header("Accept-Ranges", "bytes"); self.end_headers()
        self._left = b - a + 1
        return f
    def copyfile(self, src, dst):
        n = getattr(self, "_left", None)
        if n is None: return super().copyfile(src, dst)
        while n > 0:
            c = src.read(min(65536, n))
            if not c: break
            dst.write(c); n -= len(c)
        self._left = None

srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(Range, directory=HUB))
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/index.html"

def proj(H, x, y):
    w = H[6] * x + H[7] * y + H[8]
    return ((H[0] * x + H[1] * y + H[2]) / w, (H[3] * x + H[4] * y + H[5]) / w, w)

def err_px(Hh, Hg):
    worst = 0.0
    for i in range(15):
        for j in range(11):
            x, y = -52.5 + i * 7.5, -34 + j * 6.8
            u, v, w = proj(Hg, x, y)
            if w <= 0 or not (0 <= u <= GT["w"] and 0 <= v <= GT["h"]): continue
            a, b, _ = proj(Hh, x, y); worst = max(worst, math.hypot(a - u, b - v))
    return worst

gates, errors = [], []
def gate(name, cond, detail=""):
    gates.append((bool(cond), name, detail))

random.seed(4)
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        launch = dict(headless=True, args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--autoplay-policy=no-user-gesture-required"])
        if args.chrome: launch["executable_path"] = args.chrome
        br = p.chromium.launch(**launch)
        pg = br.new_page(viewport={"width": 1600, "height": 960})
        pg.on("console", lambda m: errors.append(f"{m.text} @ {m.location.get('url')}") if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(URL); pg.wait_for_function("window.__hubReady === true", timeout=60000)
        mods = pg.evaluate("window.__hubModules")
        gate("all hub modules load", all(v == "ok" for v in mods.values()), json.dumps(mods))
        pg.evaluate("""async (clip) => { const c = window.__hub;
          window.F = await c.need("footage"); window.T = await c.need("timeline"); window.D = await c.need("drawing"); window.A = await c.need("analytics");
          await F.open("data/" + clip); F.setMode("full"); }""", CLIP)
        pg.wait_for_timeout(800)

        def goto(t):
            pg.evaluate("t => T.seek(F.frameForVideoTime(t))", t)
            pg.wait_for_function("t => !F.video.seeking && Math.abs(F.video.currentTime - t) < 0.03", arg=t, timeout=15000)
            pg.wait_for_timeout(250)
            return pg.evaluate("F.shownTime()")

        lms = pg.evaluate("F.calibration.landmarks")
        for t in (0.42, 1.62, 2.82, 3.62):                       # four keys, clicked like a person would (+-0.7 px)
            k = round(goto(t) * GT["fps"]); H = GT["gt"][k]
            pg.evaluate("F.calibration.start()")
            for lm in lms:
                u, v, w = proj(H, lm["x"], lm["y"])
                if w > 0 and 8 < u < GT["w"] - 8 and 8 < v < GT["h"] - 8:
                    pg.evaluate("([i,u,v]) => F.calibration.add(i,u,v)", [lm["id"], u + random.uniform(-0.7, 0.7), v + random.uniform(-0.7, 0.7)])
            pg.evaluate("F.calibration.apply()")
        keys = pg.evaluate("F.calibration.keys().map(k => k.f)")
        gate("keys are stamped at the presented frames", keys == [400, 1600, 2800, 3600], str(keys))
        for ms in GT["cuts_ms"]: pg.evaluate("ms => F.cuts.mark(ms)", ms)

        for t, label, mode, max_px in ((0.42, "on a key", "key", 1.5), (0.10, "before the first key", "extrapolate", 4),
                                       (1.02, "between keys, pan", "lerp", 4), (1.30, "between keys, pan", "lerp", 4),
                                       (3.22, "between keys, pan + zoom", "lerp", 5), (3.42, "between keys, pan + zoom", "lerp", 5)):
            k = round(goto(t) * GT["fps"])
            c = pg.evaluate("(() => { const r = F.calibration.now(); return r ? { H: r.H, mode: r.mode } : null; })()")
            e = err_px(c["H"], GT["gt"][k]) if c else float("inf")
            gate(f"H(t) {label} at {t:.2f} s ({mode})", c and c["mode"] == mode and e <= max_px, f"mode={c and c['mode']} err={e:.2f}px (max {max_px})")
        goto(2.22)
        gate("no calibration inside the cut shot", pg.evaluate("F.calibration.now()") is None)
        gate("the badge says why", "No calibration in this shot" in pg.evaluate("document.querySelector('.gfoot-badge').textContent"))

        goto(1.02)
        pg.evaluate("A.setOverlay('voronoi', true)")
        k = round(pg.evaluate("F.shownTime()") * GT["fps"]); H = GT["gt"][k]
        box = pg.evaluate("""(() => { const r = F.canvas.getBoundingClientRect(), v = F.video, s = Math.min(r.width / v.videoWidth, r.height / v.videoHeight);
          return { l: r.left, t: r.top, s, ox: (r.width - v.videoWidth * s) / 2, oy: (r.height - v.videoHeight * s) / 2 }; })()""")
        def page_xy(x, y):
            u, v, _ = proj(H, x, y); return box["l"] + box["ox"] + u * box["s"], box["t"] + box["oy"] + v * box["s"]
        A_, B_ = (-25.0, -5.0), (-8.0, -20.0)
        pg.evaluate("D.setTool('rect')"); pg.wait_for_timeout(100)
        (ax, ay), (bx, by) = page_xy(*A_), page_xy(*B_)
        pg.mouse.move(ax, ay); pg.mouse.down()
        for i in range(1, 11): pg.mouse.move(ax + (bx - ax) * i / 10, ay + (by - ay) * i / 10)
        pg.mouse.up(); pg.wait_for_timeout(300)
        d = pg.evaluate("(window.__hub.store.get('drawings') || []).slice(-1)[0] || null")
        if d:
            xs = [q[0] for q in d["pts"]]; ys = [q[1] for q in d["pts"]]
            em = max(math.hypot(min(xs) - A_[0], max(ys) - A_[1]), math.hypot(max(xs) - B_[0], min(ys) - B_[1]))
        gate("a rectangle dragged on the video lands in pitch metres", d and d["kind"] == "zone" and em < 0.25, f"err={em:.3f} m" if d else "no shape")
        pg.evaluate("D.setTool('select')"); pg.wait_for_timeout(300)
        gate("the overlay warp has a renderer", pg.evaluate("F.warpMode()") in ("gl", "2d"), pg.evaluate("F.warpMode()"))
        if args.keep: pg.screenshot(path=os.path.join(OUT, "overlay_1.02s.png"))

        pg.evaluate("F.cuts.clear(); F.cuts.detect(true)")
        goto(0.0); pg.evaluate("T.play()")
        pg.wait_for_function("F.video.currentTime > 3.9 || F.video.ended", timeout=20000)
        pg.evaluate("T.pause()")
        found = pg.evaluate("F.cuts.list()")
        ok = len(found) == len(GT["cuts_ms"]) and all(abs(a - b) <= 80 for a, b in zip(found, GT["cuts_ms"]))
        gate("cut detection finds both cuts within 2 frames", ok, f"found {found}, truth {GT['cuts_ms']}")
        br.close()
finally:
    srv.shutdown()
    try: os.remove(os.path.join(HUB, "data", CLIP))
    except OSError: pass

real = [e for e in errors if "favicon.ico" not in e]
gate("no console errors", not real, "; ".join(real[:3]))
w = max(len(n) for _, n, _ in gates)
for ok, name, detail in gates: print(f"{'PASS' if ok else 'FAIL'}  {name:<{w}}  {detail}")
failed = sum(1 for g in gates if not g[0])
print(f"\n{len(gates) - failed}/{len(gates)} gates passed")
sys.exit(1 if failed else 0)
