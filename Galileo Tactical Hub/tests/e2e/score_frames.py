"""Per-frame overlay accuracy: H(t) as the hub interpolates it vs ground truth, every video frame.
usage: score_frames.py <clip.json> <gt.json> [label]"""
import json, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from galileo_data import pitch as P
from galileo_data.vision import HTimeline

sc, gt = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
W, Hh = sc["calibration"]["size"]
s = W / gt["size"][0]
tl = HTimeline(sc)
grid = np.array([(x, y) for x in np.linspace(-50, 50, 21) for y in np.linspace(-32, 32, 13)])
errs, none, modes = [], 0, {}
for i, Hg in enumerate(gt["H"]):
    ms = round(i * 1000 / gt["fps"])
    H, mode = tl.at(ms)
    if H is None:
        none += 1
        continue
    modes[mode] = modes.get(mode, 0) + 1
    G = P.scale_h(np.array(Hg).reshape(3, 3), s, s)
    a, b = P.project(G, grid), P.project(H, grid)
    vis = np.isfinite(a[:, 0]) & (a[:, 0] >= 0) & (a[:, 0] < W) & (a[:, 1] >= 0) & (a[:, 1] < Hh)
    errs.append(float(np.sqrt(np.nanmean(((a - b)[vis] ** 2).sum(1)))))
e = np.array(errs)
print(json.dumps({"label": sys.argv[3] if len(sys.argv) > 3 else "", "frames": len(gt["H"]), "covered": len(e), "uncovered": none,
                  "median_px": round(float(np.median(e)), 2), "p95_px": round(float(np.percentile(e, 95)), 2),
                  "max_px": round(float(e.max()), 2), "modes": modes}))
