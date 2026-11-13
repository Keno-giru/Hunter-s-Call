"""Unit tests for tools/galileo_data, including parity with the hub's JavaScript.

usage: python3 tests/py/test_toolkit.py      (node on PATH for the parity checks)
"""

import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

HUB = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HUB / "tools"))
from galileo_data import calibrate as C  # noqa: E402
from galileo_data import footage as F  # noqa: E402
from galileo_data import pitch as P  # noqa: E402
from galileo_data import video_track as V  # noqa: E402
from galileo_data.pack import build_pack, decode, replay_clock, video_time  # noqa: E402
from galileo_data.vision import HTimeline  # noqa: E402

passed, failed = 0, 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print("FAIL:", name, detail)


NODE = shutil.which("node")


def node(script):
    r = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=HUB, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr)
    return json.loads(r.stdout)


# ---------------------------------------------------------------- pack
rng = np.random.default_rng(1)
n, nP = 40, 5
pos = rng.uniform(-50, 50, (n, nP, 2))
pos[5:9, 2] = np.nan
det = np.ones((n, nP), np.int8)
det[10:14, 1] = 0
ball = np.c_[rng.uniform(-50, 50, (n, 2)), rng.uniform(0, 3, n)]
ball[20] = np.nan
t = np.r_[np.arange(20) * 0.1, np.arange(20) * 0.1]
period = np.r_[np.ones(20), 2 * np.ones(20)].astype(np.uint8)
players = [{"id": f"p{i}", "team": "home" if i < 3 else "away", "number": i + 1, "name": f"P{i}", "unit": "MID", "role": "CM",
            "group": "Midfield", "starter": True} for i in range(nP)]
view = np.tile([-10, -5, 10, -5, 20, 20, -20, 20], (n, 1)).astype(float)
pk = build_pack(meta={"home": {"name": "H"}, "away": {"name": "A"}}, players=players, fps=10, frame=np.arange(n) * 4 + 7, t=t,
                period=period, pos=pos, det=det, ball=ball, poss=np.arange(n) % nP - 1, view=view,
                events=[{"type": "pass", "frame_start": 15, "frame_end": 19}])
d = decode(pk)
ok("pack: positions round trip to 0.05 m", np.nanmax(np.abs(d["pos"] - pos)) <= 0.05 + 1e-9)
ok("pack: absent stays absent", np.isnan(d["pos"][5:9, 2]).all() and (d["det"][5:9, 2] == -1).all())
ok("pack: det 0 (extrapolated) survives RLE", (d["det"][10:14, 1] == 0).all() and (d["det"][:10, 1] == 1).all())
ok("pack: ball NaN row", np.isnan(d["ball"][20]).all())
ok("pack: frame numbers", list(d["frame"][:3]) == [7, 11, 15])
if NODE:
    tmp = Path(tempfile.mkdtemp()) / "p.json"
    tmp.write_text(json.dumps(pk))
    js = node(f"""
      import {{ decode }} from './js/data.js';
      import {{ makeReplayClock, videoTimeFor }} from './js/footage.js';
      import fs from 'fs';
      const r = decode(JSON.parse(fs.readFileSync('{tmp.as_posix()}', 'utf8')));
      const c = makeReplayClock(r);
      const foot = {{ offset: 2.5, offset2: 7.25, rate: 1 }};
      console.log(JSON.stringify({{ px: Array.from(r.px.slice(0, 10)), det: Array.from(r.det.slice(50, 60)), b: Array.from(r.ball.slice(57, 63)),
        poss: Array.from(r.poss.slice(0, 6)), f0: r.events[0].f0, vt: [0, 7.5, 19, 20, 33.25].map((f) => videoTimeFor(c, foot, f)) }}));""")
    ok("parity: data.js decodes the Python pack (positions)", np.allclose(js["px"], d["pos"].reshape(-1, 2)[:10, 0].astype(np.float32), atol=1e-4, equal_nan=True))
    ok("parity: det", js["det"] == d["det"].reshape(-1)[50:60].tolist())
    ok("parity: ball absent in JS too", all(v is None or (isinstance(v, float) and math.isnan(v)) for v in js["b"][3:6]), str(js["b"]))
    ok("parity: possession", js["poss"] == d["poss"][:6].tolist())
    ok("parity: event frame index", js["f0"] == 2, str(js["f0"]))
    rt = replay_clock(d)
    py_vt = [video_time(rt, d["period"], {"offset": 2.5, "offset2": 7.25, "rate": 1}, f, d["fps"]) for f in (0, 7.5, 19, 20, 33.25)]
    ok("parity: replay clock + videoTimeFor", np.allclose(js["vt"], py_vt, atol=1e-5), f"{js['vt']} vs {py_vt}")

# ---------------------------------------------------------------- homography
Htrue = np.array([[9.0, -1.2, 640], [0.4, 3.1, 420], [0.0005, -0.004, 1.0]])
src = np.array([P.xy(k) for k in ("c_lt", "c_rt", "h_t", "ctr", "pb_l_ft", "pb_r_fb", "cc_t", "ps_r")])
dst = P.project(Htrue, src)
H = P.homography(src, dst)
ok("homography: exact recovery", np.allclose(H, Htrue / Htrue[2, 2], atol=1e-6))
bad = dst.copy()
bad[2] += 80
Hr, m = P.ransac(src, bad, thresh_px=3)
ok("ransac: rejects the outlier", m is not None and not m[2] and m.sum() == 7)
ok("ransac: fit on inliers", np.allclose(P.project(Hr, src[m]), dst[m], atol=1e-3))
ok("registry: hub landmark ids present", all(k in P.BY_ID for k in ("c_lt", "sb_r_gb", "ps_l", "cc_b")))
ok("registry: flip_idx is an involution", all(P.flip_idx()[P.flip_idx()[i]] == i for i in range(len(P.IDS))))
ok("layouts: roboflow32 maps 32 known ids", len(P.ROBOFLOW_32) == 32 and all(k in P.BY_ID for k in P.ROBOFLOW_32))
ok("layouts: hamza28 maps 28 distinct ids", len(set(P.HAMZA_28.values())) == 28 and all(v in P.BY_ID for v in P.HAMZA_28.values()))

# ---------------------------------------------------------------- calibration keys from detections


def det_frame(t, ids, noise=0.0, shift=None):
    uv = P.project(Htrue, [P.xy(k) for k in ids])
    pts = []
    for k, (u, v) in zip(ids, uv):
        du = rng.normal(0, noise, 2) if noise else (0, 0)
        if shift and k in shift:
            du = (du[0] + shift[k][0], du[1] + shift[k][1])
        pts.append((k, u + du[0], v + du[1], 0.9))
    return {"t_ms": t, "points": pts}


four = det_frame(0, ["c_lt", "c_rt", "pb_l_ft", "ctr"], shift={"ctr": (40, 0)})
line = det_frame(500, ["h_t", "cc_t", "ctr", "cc_b", "h_b"])
good = det_frame(1000, ["c_lt", "c_rt", "h_t", "ctr", "pb_l_ft", "pb_r_fb", "cc_t", "ps_r"], noise=0.5)
keys, rep = C.keys_from_detections([four, line, good], size=(1280, 720))
ok("keys: 4 points never make a key (one could be wrong)", rep["rejected"]["few_points"] >= 1)
ok("keys: points on one line are rejected", rep["rejected"]["collinear"] + rep["rejected"]["unstable"] + rep["rejected"]["ransac"] >= 1, json.dumps(rep))
ok("keys: a good spread frame makes one key", len(keys) == 1 and keys[0]["f"] == 1000)
ok("keys: merge replaces auto keys, keeps manual", [k["f"] for k in C.merge_keys([{"f": 5, "H": [1] * 9}, {"f": 9, "H": [1] * 9, "auto": True}], keys, mode="replace")] == [5, 1000])

# ---------------------------------------------------------------- H timeline
H0, H1 = np.eye(3), np.array([[2.0, 0, 10], [0, 2.0, 20], [0, 0, 1.0]])
sc = {"calibration": {"keys": [{"f": 0, "H": H0.reshape(-1).tolist()}, {"f": 1000, "H": H1.reshape(-1).tolist()},
                               {"f": 3000, "H": H1.reshape(-1).tolist()}], "fixed": False}, "cuts_ms": [2000]}
tl = HTimeline(sc)
ok("timeline: element-wise blend at the midpoint", np.allclose(tl.at(500)[0], (H0 + H1) / 2) and tl.at(500)[1] == "lerp")
ok("timeline: never blends across a cut", tl.at(2500)[1] in ("hold",) and np.allclose(tl.at(2500)[0], H1))
ok("timeline: holds at most 2 s", tl.at(1000 + 1900)[0] is None or tl.at(1000 + 1900)[1] != "lerp")
s2 = F.keys_for_size({"calibration": {"size": [1280, 720], "keys": [{"f": 0, "H": Htrue.reshape(-1).tolist()}]}}, 640, 360)
ok("sidecar: keys rescale with the video", np.allclose(P.project(np.array(s2[0]["H"]).reshape(3, 3), src), dst / 2, atol=1e-6))

# ---------------------------------------------------------------- cut detector parity (Python vs js/calib.js)


def frames_seq(seed):
    r = np.random.default_rng(seed)
    base = np.zeros((9, 16, 3), np.uint8)
    base[..., 1] = 120
    base[..., 0] = 40
    other = base.copy()
    other[:, :, 1] = 70                                       # another camera: darker grass, a line in view
    other[:, 6:8] = 235
    seq = []
    for i in range(80):
        f = (base if i < 40 else other).astype(int) + r.integers(-3, 4, (9, 16, 3))
        if 20 <= i < 30:                                     # a pan: a bright line sweeping across
            f[:, (i - 20) % 16] = 230
        seq.append(np.clip(f, 0, 255).astype(np.uint8))
    return seq


seq = frames_seq(3)
det_py = F.CutDetector()
py_cuts = [c for i, fr in enumerate(seq) if (c := det_py.push(F.frame_signature(fr), i * 40)) is not None]
if NODE:
    rgba = [np.dstack([fr, np.full((9, 16), 255, np.uint8)]).reshape(-1).tolist() for fr in seq]
    tmpf = Path(tempfile.mkdtemp()) / "frames.json"
    tmpf.write_text(json.dumps(rgba))
    js_cuts = node(f"""
      import {{ frameSignature, createCutDetector }} from './js/calib.js';
      import fs from 'fs';
      const fr = JSON.parse(fs.readFileSync('{tmpf.as_posix()}', 'utf8'));
      const d = createCutDetector(); const out = [];
      fr.forEach((px, i) => {{ const c = d.push(frameSignature(new Uint8ClampedArray(px)), i * 40); if (c !== false) out.push(c); }});
      console.log(JSON.stringify(out));""")
    ok("parity: Python and JS cut detectors agree", js_cuts == py_cuts, f"js {js_cuts} py {py_cuts}")
ok("cuts: the camera change is found, the pan is not", py_cuts == [1600], str(py_cuts))

# ---------------------------------------------------------------- tracker in metres
lab_red, lab_blue = np.array([120.0, 180, 160]), np.array([90.0, 140, 70])


def crossing(kit_a, kit_b):
    frames = []
    for i in range(50):
        t = i * 40
        xa, xb = -5 + 0.2 * i, 5 - 0.2 * i                    # head-on, passing within 0.4 m
        frames.append((t, [(xa, 0.2, 0.9, (0, 0, 1, 1, kit_a), "player"), (xb, -0.2, 0.9, (0, 0, 1, 1, kit_b), "player")]))
    return V.track_players(frames)


tr = crossing(lab_red, lab_blue)
ends = sorted(tr, key=lambda x: x.x[0])
ok("tracker: two kits crossing keep their identities", len(tr) == 2 and ends[0].x[-1] > 4 and ends[1].x[-1] < -4,
   str([(round(a.x[0], 1), round(a.x[-1], 1)) for a in tr]))
tr = crossing(lab_red, lab_red)
ends = sorted(tr, key=lambda x: x.x[0])
ok("tracker: same kit crossing follows momentum", len(tr) == 2 and ends[0].x[-1] > 4, str([(round(a.x[0], 1), round(a.x[-1], 1)) for a in tr]))
frag = [(i * 40, [(0.1 * i, 0.0, 0.9, (0, 0, 1, 1, lab_red), "player")]) for i in range(30)] + \
       [(3200 + i * 40, [(13.0 + 0.1 * i, 0.3, 0.9, (0, 0, 1, 1, lab_red), "player")]) for i in range(30)]
tr = V.track_players(frag)                                    # 2 s unseen (longer than the tracker's 1.2 s), ~5 m/s
for x in tr:
    x.colours = [b[4] for b in x.box]
ok("stitch: a 2 s gap at running pace is one player", len(tr) == 2 and len(V.stitch(tr)) == 1, f"{len(tr)} -> {len(V.stitch(tr))}")
bs = V.ball_series([0, 40, 80, 120, 160], [(0, (0.0, 0.0)), (40, (30.0, 0.0)), (80, None), (120, (0.6, 0.0)), (160, (0.8, 0.0))])
ok("ball: a 750 m/s jump is rejected and the gap filled", np.isfinite(bs[1, 0]) and abs(bs[1, 0] - 0.2) < 0.05, str(bs[:, 0]))
st = V.player_stats([{"id": "a", "team": "home", "unit": "MID"}],
                    np.c_[np.arange(100) * 0.8, np.zeros(100)].reshape(100, 1, 2), np.ones((100, 1), np.int8), 0.1)
ok("stats: 8 m/s run gives 79 m, top 8 m/s, one sprint", abs(st[0]["distance_m"] - 79.2) < 1.5 and abs(st[0]["top_speed_m_s"] - 8) < 0.2
   and st[0]["sprints"] == 1, json.dumps(st[0]))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
