"""Synthetic broadcast footage rendered from a hub pack, with exact ground truth.

A pinhole camera on the near stand follows the ball (pan + zoom); a close-up from a second camera
sits between two hard cuts; the video starts LEAD seconds before kick-off. Writes:
  <out>/broadcast.mp4   1920x1080, 25 fps, H.264
  <out>/broadcast_gt.json   per-frame H (pitch m -> px), cuts_ms, kickoff_s, size
  <out>/detections.jsonl    simulated pitch-keypoint detector output on the 1280x720 proxy (noise + outliers)
  <out>/boxes.jsonl         simulated object detector on the proxy: player / goalkeeper / ball boxes with
                            jitter, 8% misses, false positives; goalkeepers wear their own kit colours

usage: python gen_broadcast.py <pack.ghp.json> <out dir> [seconds]
"""

import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from galileo_data import pitch as P  # noqa: E402
from galileo_data.pack import decode, load, replay_clock  # noqa: E402

W, H, FPS, LEAD = 1920, 1080, 25, 3.0
CUT_A, CUT_B = 8.0, 10.0           # close-up between these video times


def camera(C, target, f):
    fwd = np.asarray(target, float) - C
    fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, [0, 0, 1.0])
    right /= np.linalg.norm(right)
    down = np.cross(fwd, right)
    R = np.stack([right, down, fwd])
    K = np.array([[f, 0, W / 2], [0, f, H / 2], [0, 0, 1]])
    Pm = K @ R @ np.c_[np.eye(3), -C]
    Hm = Pm[:, [0, 1, 3]]
    return Pm, Hm / Hm[2, 2]


def proj3(Pm, X):
    q = Pm @ np.r_[X, 1.0]
    return (q[0] / q[2], q[1] / q[2]) if q[2] > 0.1 else None


def pitch_polylines():
    L, Wd = P.HALF_L, P.HALF_W
    lines = [[(-L, -Wd), (L, -Wd), (L, Wd), (-L, Wd), (-L, -Wd)], [(0, -Wd), (0, Wd)]]
    for s in (-1, 1):
        g = s * L
        lines.append([(g, P.PB_HALF), (s * (L - P.PB_DEPTH), P.PB_HALF), (s * (L - P.PB_DEPTH), -P.PB_HALF), (g, -P.PB_HALF)])
        lines.append([(g, P.SB_HALF), (s * (L - P.SB_DEPTH), P.SB_HALF), (s * (L - P.SB_DEPTH), -P.SB_HALF), (g, -P.SB_HALF)])
    circ = [(P.CIRCLE * math.cos(a), P.CIRCLE * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 64)]
    lines.append(circ)
    out = []
    for pl in lines:                    # densify so projected lines bend correctly near the frame edge
        dense = []
        for (x0, y0), (x1, y1) in zip(pl[:-1], pl[1:]):
            n = max(2, int(math.hypot(x1 - x0, y1 - y0) / 1.0))
            dense += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(n)]
        dense.append(pl[-1])
        out.append(np.array(dense))
    return out


def main():
    pack_path, out = Path(sys.argv[1]), Path(sys.argv[2])
    secs = float(sys.argv[3]) if len(sys.argv) > 3 else 20.0
    out.mkdir(parents=True, exist_ok=True)
    dec = decode(load(pack_path))
    rt = replay_clock(dec)
    fps_p = dec["fps"]
    pos, ball, players = dec["pos"], dec["ball"], dec["players"]
    home_c, away_c = (214, 69, 69), (47, 111, 214)
    gk_c = {"home": (236, 200, 40), "away": (28, 28, 28)}
    rng_b = np.random.default_rng(11)
    sb = 1280 / W
    box_rows = []
    lines = pitch_polylines()

    def sample(tv):
        r = max(rt[0], tv - LEAD + rt[0])          # replay time shown at video time tv (kick-off at LEAD)
        f = (r - rt[0]) * fps_p
        f0 = int(min(len(rt) - 2, max(0, math.floor(f))))
        a = min(1.0, max(0.0, f - f0))
        p0, p1 = pos[f0], pos[f0 + 1]
        p = np.where(np.isfinite(p0), p0 + (np.nan_to_num(p1, nan=0) - np.nan_to_num(p0, nan=0)) * a, p1)
        b = ball[f0] + (np.nan_to_num(ball[f0 + 1]) - np.nan_to_num(ball[f0])) * a
        return p, b

    C_main, C_close = np.array([0.0, -48.0, 17.0]), np.array([-6.0, -40.0, 12.0])
    target = np.array([0.0, 0.0, 0.0])
    n = int(secs * FPS)
    gt_H = []
    proc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                             "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                             str(out / "broadcast.mp4")], stdin=subprocess.PIPE)
    stripes = np.linspace(-P.HALF_L, P.HALF_L, 13)
    for i in range(n):
        tv = i / FPS
        p, b = sample(tv)
        bx, by = (b[0], b[1]) if np.isfinite(b[0]) else (0.0, 0.0)
        tgt = np.array([np.clip(bx, -35, 35), np.clip(by * 0.5, -12, 12), 0.0])
        target = target + (tgt - target) * 0.06 if i else tgt     # smooth follow
        close = CUT_A <= tv < CUT_B
        if close:
            Pm, Hm = camera(C_close, [bx, by, 0.0], 3600.0)
        else:
            zoom = 1550.0 + 250.0 * math.sin(tv * 0.6)
            Pm, Hm = camera(C_main, target, zoom)
        gt_H.append([float(v) for v in Hm.reshape(-1)])
        im = Image.new("RGB", (W, H), (34, 92, 44))
        dr = ImageDraw.Draw(im)
        for k in range(len(stripes) - 1):                        # mowing stripes
            if k % 2:
                quad = P.project(Hm, [(stripes[k], -P.HALF_W - 3), (stripes[k + 1], -P.HALF_W - 3), (stripes[k + 1], P.HALF_W + 3), (stripes[k], P.HALF_W + 3)])
                if np.isfinite(quad).all():
                    dr.polygon([tuple(q) for q in quad], fill=(40, 104, 50))
        for pl in lines:
            q = P.project(Hm, pl)
            seg = []
            for u, v in q:
                if np.isfinite(u) and abs(u) < 3 * W and abs(v) < 3 * H:
                    seg.append((u, v))
                elif len(seg) > 1:
                    dr.line(seg, fill=(235, 240, 235), width=3)
                    seg = []
                else:
                    seg = []
            if len(seg) > 1:
                dr.line(seg, fill=(235, 240, 235), width=3)
        order = sorted(range(len(players)), key=lambda j: -(p[j, 1] if np.isfinite(p[j, 1]) else -99))
        boxes = []
        for j in order:
            if not np.isfinite(p[j, 0]):
                continue
            foot, head = proj3(Pm, [p[j, 0], p[j, 1], 0.0]), proj3(Pm, [p[j, 0], p[j, 1], 1.8])
            if not foot or not head:
                continue
            hgt = foot[1] - head[1]
            wd = max(2.0, hgt * 0.28)
            gk = players[j].get("unit") == "GK"
            col = gk_c[players[j]["team"]] if gk else (home_c if players[j]["team"] == "home" else away_c)
            dr.ellipse([foot[0] - wd, head[1], foot[0] + wd, foot[1]], fill=col, outline=(15, 15, 15))
            x1, y1, x2, y2 = (foot[0] - wd) * sb, head[1] * sb, (foot[0] + wd) * sb, foot[1] * sb
            if x2 > 0 and x1 < 1280 and y2 > 0 and y1 < 720 and rng_b.random() > 0.08:
                jx = rng_b.normal(0, 1.5, 4)
                boxes.append({"cls": "goalkeeper" if gk else "player", "x1": round(max(0, x1 + jx[0]), 1), "y1": round(max(0, y1 + jx[1]), 1),
                              "x2": round(min(1280, x2 + jx[2]), 1), "y2": round(min(720, y2 + jx[3]), 1),
                              "conf": round(float(rng_b.uniform(0.5, 0.95)), 2), "gt": j})
        if np.isfinite(b[0]):
            bp = proj3(Pm, [b[0], b[1], max(0.11, float(b[2]))])
            if bp:
                r = max(2.0, 0.11 * (Pm[0, 0] / 40.0) / 3.0)
                dr.ellipse([bp[0] - r, bp[1] - r, bp[0] + r, bp[1] + r], fill=(250, 250, 250), outline=(20, 20, 20))
                if 0 <= bp[0] < W and 0 <= bp[1] < H and rng_b.random() < 0.7:
                    u, v = bp[0] * sb + rng_b.normal(0, 1.0), bp[1] * sb + rng_b.normal(0, 1.0)
                    rr = max(2.0, r * sb)
                    boxes.append({"cls": "ball", "x1": round(u - rr, 1), "y1": round(v - rr, 1), "x2": round(u + rr, 1), "y2": round(v + rr, 1),
                                  "conf": round(float(rng_b.uniform(0.3, 0.9)), 2)})
        if rng_b.random() < 0.3:                                  # false positive somewhere on the pitch
            u, v = rng_b.uniform(50, 1230), rng_b.uniform(200, 700)
            boxes.append({"cls": "player", "x1": round(u - 10, 1), "y1": round(v - 45, 1), "x2": round(u + 10, 1), "y2": round(v, 1), "conf": 0.31})
        if rng_b.random() < 0.02:
            u, v = rng_b.uniform(50, 1230), rng_b.uniform(200, 700)
            boxes.append({"cls": "ball", "x1": round(u - 3, 1), "y1": round(v - 3, 1), "x2": round(u + 3, 1), "y2": round(v + 3, 1), "conf": 0.35})
        box_rows.append({"frame": i, "t_ms": int(round(tv * 1000)), "boxes": boxes})
        proc.stdin.write(im.tobytes())
    proc.stdin.close()
    proc.wait()
    gt = {"size": [W, H], "fps": FPS, "kickoff_s": LEAD, "cuts_ms": [int(CUT_A * 1000), int(CUT_B * 1000)], "H": gt_H}
    with open(out / "boxes.jsonl", "w") as fh:
        for row in box_rows:
            fh.write(json.dumps(row) + "\n")
    (out / "broadcast_gt.json").write_text(json.dumps(gt))

    # simulated detector on the 1280x720 proxy, every 500 ms: 1.2 px noise, 12% gross outliers, 20% dropouts
    rng = np.random.default_rng(7)
    s = 1280 / W
    src = np.array([[k["x"], k["y"]] for k in P.KEYPOINTS])
    with open(out / "detections.jsonl", "w") as fh:
        for ms in range(0, int(secs * 1000), 500):
            Hm = P.scale_h(np.array(gt_H[min(n - 1, round(ms / 1000 * FPS))]).reshape(3, 3), s, s)
            uv = P.project(Hm, src)
            pts = []
            for k, (u, v) in zip(P.KEYPOINTS, uv):
                if not (np.isfinite(u) and 0 <= u < 1280 and 0 <= v < 720) or rng.random() < 0.2:
                    continue
                if rng.random() < 0.12:
                    u, v = u + rng.normal(0, 60), v + rng.normal(0, 60)
                else:
                    u, v = u + rng.normal(0, 1.2), v + rng.normal(0, 1.2)
                pts.append({"id": k["id"], "u": round(float(u), 2), "v": round(float(v), 2), "conf": round(float(rng.uniform(0.6, 0.99)), 3)})
            fh.write(json.dumps({"t_ms": ms, "points": pts}) + "\n")
    print(f"{n} frames -> {out / 'broadcast.mp4'}")


if __name__ == "__main__":
    main()
