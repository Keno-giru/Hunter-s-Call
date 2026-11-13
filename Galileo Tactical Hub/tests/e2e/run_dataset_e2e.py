"""End-to-end gates for the dataset workflow in the real hub (Playwright + Chrome).

Needs the synthetic broadcast pipeline to have run first (see tests/README or CHANGES.md):
  convert metrica --game 1; gen_broadcast.py; ingest --match metrica-sample-1 --kickoff 3.0;
  calibrate; camera; track.
usage: python3 tests/e2e/run_dataset_e2e.py [--chrome /usr/bin/google-chrome]
H.264 proxies need real Chrome (Playwright's bundled Chromium has no H.264). Exit 0 = all gates pass.
"""

import argparse
import json
import math
import os
import sys
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

HUB = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HUB / "tools"))
from serve import Handler  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--chrome", default=os.environ.get("CHROME") or "/usr/bin/google-chrome")
ap.add_argument("--out", default=str(HUB / "tests" / "e2e" / "out"))
args = ap.parse_args()

CLIP_DIR = "datasets/matches/metrica-sample-1/footage/synth-broadcast"
PROVIDER = "datasets/matches/metrica-sample-1/pack.ghp.json"
VIDEO_PACK = "datasets/matches/video-synth-broadcast/pack.ghp.json"
SC = json.loads((HUB / CLIP_DIR / "clip.json").read_text())
GT = json.loads((HUB / "tests/e2e/out/broadcast/broadcast_gt.json").read_text())
S = SC["calibration"]["size"][0] / GT["size"][0]

srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(HUB)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}/"

gates, errors = [], []


def gate(name, ok, detail=""):
    gates.append((bool(ok), name, detail))


def proj(H, x, y):
    w = H[6] * x + H[7] * y + H[8]
    return (H[0] * x + H[1] * y + H[2]) / w, (H[3] * x + H[4] * y + H[5]) / w, w


def gt_h(ms):
    H = GT["H"][min(len(GT["H"]) - 1, round(ms / 1000 * GT["fps"]))]
    return [H[0] * S, H[1] * S, H[2] * S, H[3] * S, H[4] * S, H[5] * S, H[6], H[7], H[8]]


def rms_px(Hh, Hg, W=1280, Hgt=720):
    acc, n = 0.0, 0
    for i in range(21):
        for j in range(13):
            x, y = -50 + i * 5, -32 + j * 64 / 12
            u, v, w = proj(Hg, x, y)
            if w * Hg[8] <= 0 or not (0 <= u < W and 0 <= v < Hgt):
                continue
            a, b, _ = proj(Hh, x, y)
            acc += (a - u) ** 2 + (b - v) ** 2
            n += 1
    return math.sqrt(acc / n) if n else float("nan")


from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as p:
    br = p.chromium.launch(headless=True, executable_path=args.chrome,
                           args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--autoplay-policy=no-user-gesture-required"])
    pg = br.new_page(viewport={"width": 1600, "height": 960})
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" and "favicon" not in m.text else None)
    pg.on("pageerror", lambda e: errors.append(str(e)))

    # 1. provider pack + footage from the URL; clip.json found next to the video
    pg.goto(f"{BASE}index.html?pack={PROVIDER}&footage={CLIP_DIR}/proxy.mp4")
    pg.wait_for_function("window.__hubReady === true && window.__hubFootage", timeout=90000)
    gate("hub modules load", all(v == "ok" for v in pg.evaluate("window.__hubModules").values()))
    gate("footage opened from ?footage=", pg.evaluate("window.__hubFootage") == "ok", pg.evaluate("window.__hubFootage"))
    pg.evaluate("async () => { window.F = await __hub.need('footage'); window.T = await __hub.need('timeline'); F.setMode('full'); }")
    meta = pg.evaluate("({ id: __hub.store.get('replay').meta.match_id, n: __hub.store.get('replay').n })")
    gate("?pack= loads the dataset pack", meta["id"] == "metrica-sample-1" and meta["n"] > 70000, json.dumps(meta))
    keys = pg.evaluate("F.calibration.keys().length")
    gate("clip.json keys imported", keys == len(SC["calibration"]["keys"]), f"{keys} vs {len(SC['calibration']['keys'])}")
    gate("clip.json cuts imported", pg.evaluate("F.cuts.list()") == SC["cuts_ms"], str(pg.evaluate("F.cuts.list()")))
    vt0 = pg.evaluate("F.videoTime(0)")
    gate("sync: kick-off frame plays at 3.0 s of video", abs(vt0 - 3.0) < 0.02, f"{vt0:.3f}")
    worst = 0.0
    for ms in (1000, 4300, 5600, 12700, 17100):
        H = pg.evaluate("ms => F.calibration.at(ms)?.H", ms)
        e = rms_px(H, gt_h(ms)) if H else float("inf")
        worst = max(worst, e)
    gate("hub H(t) matches the camera (5 moments, RMS px)", worst < 12, f"worst {worst:.2f} px")
    gate("no calibration inside the close-up shot", pg.evaluate("F.calibration.at(9000)") is None or
         pg.evaluate("F.calibration.at(9000)?.weak") is True, str(pg.evaluate("F.calibration.at(9000)?.mode")))

    def show(t):
        pg.evaluate("t => T.seek(F.frameForVideoTime(t))", t)
        pg.wait_for_function("t => !F.video.seeking && Math.abs(F.video.currentTime - t) < 0.05", arg=t, timeout=20000)
        pg.wait_for_timeout(400)

    show(5.6)
    pg.screenshot(path=f"{args.out}/dataset_provider_overlay.png")
    gate("overlay warps on the GPU", pg.evaluate("F.warpMode()") == "gl", pg.evaluate("F.warpMode()"))

    # 2. export round trip and import
    ex = pg.evaluate("F.sidecar.export()")
    gate("export keeps tool fields (labels, provenance)", len(ex["labels"]) == len(SC["labels"]) and ex["provenance"]["rights_confirmed"])
    gate("export carries keys, cuts and sync", len(ex["calibration"]["keys"]) == keys and ex["cuts_ms"] == SC["cuts_ms"]
         and abs(ex["sync"]["offset"] - SC["sync"]["offset"]) < 1e-9, json.dumps(ex["sync"]))
    gate("export marks the calibration size", ex["calibration"]["size"] == [1280, 720], str(ex["calibration"]["size"]))
    half = dict(ex)
    half["calibration"] = dict(ex["calibration"], keys=ex["calibration"]["keys"][::2], size=[640, 360])
    for k in half["calibration"]["keys"]:
        k["H"] = [k["H"][0] / 2, k["H"][1] / 2, k["H"][2] / 2, k["H"][3] / 2, k["H"][4] / 2, k["H"][5] / 2, k["H"][6], k["H"][7], k["H"][8]]
    pg.evaluate("sc => F.sidecar.import(sc, { quiet: true })", half)
    H = pg.evaluate("F.calibration.at(4300)?.H")
    gate("import rescales keys from another resolution", H is not None and rms_px(H, gt_h(4300)) < 15,
         f"{rms_px(H, gt_h(4300)):.2f} px" if H else "none")
    ls_keys = pg.evaluate("Object.keys(localStorage).filter(k => k.includes('clip:'))")
    gate("local edits are stored per video path", any("synth-broadcast/proxy.mp4" in k for k in ls_keys), str(ls_keys))

    # 3. the video-derived pack on the same footage and clip.json
    pg2 = br.new_page(viewport={"width": 1600, "height": 960})
    pg2.on("pageerror", lambda e: errors.append(str(e)))
    pg2.goto(f"{BASE}index.html?pack={VIDEO_PACK}&footage={CLIP_DIR}/proxy.mp4&view=video")
    pg2.wait_for_function("window.__hubReady === true && window.__hubFootage", timeout=90000)
    pg2.evaluate("async () => { window.F = await __hub.need('footage'); window.T = await __hub.need('timeline'); localStorage.clear(); }")
    vm = pg2.evaluate("({ src: __hub.store.get('replay').meta.source, nP: __hub.store.get('replay').nP })")
    gate("video-derived pack loads", vm["src"] == "video" and vm["nP"] > 10, json.dumps(vm))
    f = pg2.evaluate("F.frameForVideoTime(5.6)")
    vt = pg2.evaluate("f => F.videoTime(f)", f)
    gate("video pack shares the clip's clock", abs(vt - 5.6) < 0.1, f"frame {f}, video {vt:.3f} s")
    pg2.evaluate("t => T.seek(F.frameForVideoTime(t))", 5.6)
    pg2.wait_for_function("!F.video.seeking && Math.abs(F.video.currentTime - 5.6) < 0.08", timeout=20000)
    pg2.wait_for_timeout(500)
    pg2.screenshot(path=f"{args.out}/dataset_video_pack_overlay.png")

    # 4. bad pack path falls back to the sample, library page renders
    pg3 = br.new_page()
    pg3.goto(f"{BASE}index.html?pack=datasets/nope.ghp.json")
    pg3.wait_for_function("window.__hubReady === true", timeout=90000)
    gate("missing ?pack= falls back to the sample", pg3.evaluate("__hub.store.get('replay').meta.match_id") == 1925299)
    pg3.goto(f"{BASE}datasets/index.html")
    links = pg3.evaluate("[...document.querySelectorAll('a')].map(a => a.getAttribute('href'))")
    gate("library page links matches and clips", any("video-synth-broadcast" in (h or "") for h in links)
         and any("footage=" in (h or "") for h in links), f"{len(links)} links")
    br.close()

srv.shutdown()
real_errors = [e for e in errors if "nope.ghp.json" not in e and "404" not in e]
gate("no page errors", not real_errors, "; ".join(real_errors[:3]))
for ok, name, detail in gates:
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
fails = sum(1 for g in gates if not g[0])
print(f"\n{len(gates) - fails}/{len(gates)} gates passed")
sys.exit(1 if fails else 0)
