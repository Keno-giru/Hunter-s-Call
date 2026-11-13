# Usage: python3 tests/e2e/gen_clip.py [outdir]   (needs numpy, opencv-python, ffmpeg on PATH)
# Synthetic broadcast clip with exact ground truth.
# 0.0-2.0 s  shot A: wide camera pans right      (pan -0.10 -> +0.02 rad)
# 2.0-2.5 s  shot B: hard cut to a close-up (no pitch markings visible)
# 2.5-4.0 s  shot C: wide camera pans left + zooms (pan +0.06 -> -0.04, zoom 1.00 -> 1.15)
import json, math, os, subprocess, sys
import numpy as np, cv2
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(OUT, exist_ok=True)
FPS, N, W, H = 25, 100, 1280, 720
PX = 10                                  # texture px per metre
TW, TH = (105 + 10) * PX, (68 + 10) * PX

def cam(pan, zoom=1.0, tilt=0.78, h=25.0, dist=62.0):
    f, cx, cy = 900 * zoom, W / 2, H / 2
    c, s, ct, st = math.cos(pan), math.sin(pan), math.cos(tilt), math.sin(tilt)
    R = np.array([[c, s, 0], [-s * st, c * st, -ct], [s * ct, -c * ct, -st]])
    t = np.array([0, h * ct, dist])
    M = np.column_stack([R[:, 0], R[:, 1], t])
    Hm = np.array([[f, 0, cx], [0, f, cy], [0, 0, 1]]) @ M
    return Hm / Hm[2, 2]

def shot(t):
    if t < 2.0: a = t / 2.0; return "A", cam(-0.10 + 0.12 * a)
    if t < 2.5: return "B", None
    a = (t - 2.5) / 1.5; return "C", cam(0.06 - 0.10 * a, 1.0 + 0.15 * a)

# top-down pitch texture
tex = np.zeros((TH, TW, 3), np.uint8); tex[:] = (38, 92, 46)                     # BGR margin
def P(x, y): return (int(round((x + 57.5) * PX)), int(round((39 - y) * PX)))
for i in range(18):
    x0, x1 = -52.5 + i * 105 / 18, -52.5 + (i + 1) * 105 / 18
    cv2.rectangle(tex, P(x0, 34), P(x1, -34), (52, 128, 62) if i % 2 else (46, 116, 56), -1)
L = (235, 240, 238)
def line(a, b): cv2.line(tex, P(*a), P(*b), L, 3, cv2.LINE_AA)
def rect(x0, y0, x1, y1): line((x0, y0), (x1, y0)); line((x1, y0), (x1, y1)); line((x1, y1), (x0, y1)); line((x0, y1), (x0, y0))
rect(-52.5, -34, 52.5, 34); line((0, 34), (0, -34))
cv2.circle(tex, P(0, 0), int(9.15 * PX), L, 3, cv2.LINE_AA)
for s in (-1, 1):
    rect(s * 52.5, -20.16, s * 36, 20.16); rect(s * 52.5, -9.16, s * 47, 9.16)
    cv2.circle(tex, P(s * 41.5, 0), 4, L, -1)
cv2.circle(tex, P(0, 0), 4, L, -1)
G_inv = np.array([[1 / PX, 0, -57.5], [0, -1 / PX, 39], [0, 0, 1]])           # texture px -> pitch m

rng = np.random.default_rng(3)
closeup = cv2.resize(rng.integers(30, 220, (9, 16, 3), dtype=np.uint8), (W, H), interpolation=cv2.INTER_CUBIC)
closeup = cv2.GaussianBlur(closeup, (0, 0), 25)

gt, frames = [], []
for k in range(N):
    t = k / FPS
    name, Hc = shot(t)
    if Hc is None:
        img = closeup.copy(); gt.append(None)
    else:
        img = cv2.warpPerspective(tex, Hc @ G_inv, (W, H), flags=cv2.INTER_LINEAR, borderValue=(70, 52, 40))
        gt.append([float(v) for v in Hc.flatten()])
    cv2.putText(img, f"{name}  t={t:.2f}s  f{k}", (16, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
    frames.append(img)
    if k in (10, 50, 80): cv2.imwrite(os.path.join(OUT, f"frame_{k:03d}.png"), img)

enc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                        "-c:v", "libvpx-vp9", "-b:v", "3M", "-deadline", "realtime", "-cpu-used", "8", "-g", "1", "-pix_fmt", "yuv420p",
                        os.path.join(OUT, "test_pan.webm")], stdin=subprocess.PIPE)
for f in frames: enc.stdin.write(f.tobytes())
enc.stdin.close(); enc.wait()
json.dump({"fps": FPS, "w": W, "h": H, "gt": gt, "cuts_ms": [2000, 2500]}, open(os.path.join(OUT, "gt.json"), "w"))
print("frames", N, "encoder exit", enc.returncode)
# where do the corners land at t=0 / 1.0 / 3.2? (sanity: wide broadcast framing)
for t in (0.0, 1.0, 3.2):
    _, Hc = shot(t)
    pts = [(Hc @ np.array([x, y, 1.0])) for x, y in [(-52.5, 34), (52.5, 34), (52.5, -34), (-52.5, -34), (0, 0)]]
    print(t, [(round(p[0] / p[2]), round(p[1] / p[2])) for p in pts])
