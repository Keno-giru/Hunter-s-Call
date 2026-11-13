"""Score a clip's calibration keys against the synthetic ground truth. usage: score_keys.py <clip.json> <gt.json>"""
import json, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from galileo_data import pitch as P

sc, gt = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
W, Hh = sc["calibration"]["size"]
s = W / gt["size"][0]
grid = np.array([(x, y) for x in np.linspace(-50, 50, 21) for y in np.linspace(-32, 32, 13)])
errs = []
for k in sc["calibration"]["keys"]:
    Hg = P.scale_h(np.array(gt["H"][min(len(gt["H"]) - 1, round(k["f"] / 1000 * gt["fps"]))]).reshape(3, 3), s, s)
    a, b = P.project(Hg, grid), P.project(np.array(k["H"]).reshape(3, 3), grid)
    vis = np.isfinite(a[:, 0]) & (a[:, 0] >= 0) & (a[:, 0] < W) & (a[:, 1] >= 0) & (a[:, 1] < Hh)
    if vis.sum():
        errs.append((k["f"], float(np.sqrt(np.mean(((a - b)[vis] ** 2).sum(1))))))
e = np.array([x[1] for x in errs])
print(json.dumps({"keys": len(e), "cuts": sc.get("cuts_ms"), "gt_cuts": gt["cuts_ms"], "median_px": round(float(np.median(e)), 2),
                  "p95_px": round(float(np.percentile(e, 95)), 2), "max_px": round(float(e.max()), 2),
                  "worst": [(f, round(v, 1)) for f, v in sorted(errs, key=lambda x: -x[1])[:3]]}))
