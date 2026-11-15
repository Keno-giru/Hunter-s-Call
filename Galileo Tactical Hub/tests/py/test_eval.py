"""Tests for eval/realset.py (T1 exam tooling): extract + pre-labels, label QA, leakage, freeze, verify.

usage: python tests/py/test_eval.py
Self-contained: renders a tiny clip with a known homography in a temp folder; never touches eval/real or the manifest.
"""

import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

import numpy as np

HUB = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HUB / "tools"))
sys.path.insert(0, str(HUB / "eval"))
import cv2  # noqa: E402
import realset as R  # noqa: E402
from galileo_data import pitch as P  # noqa: E402

passed, failed = 0, 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print("FAIL:", name, detail)


W, H, FPS = 1280, 720, 10
Htrue = P.homography([(-30, 30), (30, 30), (40, -34), (-40, -34)], [(200, 100), (1080, 100), (1260, 700), (20, 700)])
rng = np.random.default_rng(3)

tmp = Path(tempfile.mkdtemp(prefix="galileo_eval_"))
try:
    # ------------------------------------------------------------ a clip with a known H
    video = tmp / "clip.mp4"
    vw = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    for i in range(30):
        img = cv2.resize(rng.integers(0, 255, (9, 16, 3), dtype=np.uint8), (W, H), interpolation=cv2.INTER_NEAREST)
        vw.write(img)
    vw.release()
    boxes = tmp / "boxes.jsonl"
    boxes.write_text("".join(json.dumps({"frame": f, "t_ms": f * 100, "boxes": [
        {"cls": "player", "x1": 100, "y1": 200, "x2": 130, "y2": 260, "conf": 0.9},
        {"cls": "ball", "x1": 400, "y1": 400, "x2": 408, "y2": 408, "conf": 0.5}]}) + "\n" for f in range(30)))
    sc = tmp / "clip.json"
    sc.write_text(json.dumps({"calibration": {"size": [W, H], "fixed": True,
                                              "keys": [{"f": 0, "H": Htrue.flatten().tolist(), "err": None}]}, "cuts_ms": []}))
    root = tmp / "real"
    out, n = R.extract(video, "c1", "unit test render", "test", every_s=0.5, boxes=boxes, clip_json=sc, root=root)
    rows = R.read_labels(out)
    ok("extract: 6 frames at 0.5 s from a 3 s clip", n == 6 and len(rows) == 6, str(n))
    ok("extract: images written with sha256", all((out / r["image"]).exists() and r["sha256"] == R.sha256_file(out / r["image"]) for r in rows))
    ok("extract: boxes pre-labelled, team and id empty", rows[0]["boxes"][0]["cls"] == "player" and rows[0]["boxes"][0]["team"] is None)
    vis = [k for k in P.KEYPOINTS if np.isfinite(P.project(Htrue, [(k["x"], k["y"])])[0, 0])
           and 0 <= P.project(Htrue, [(k["x"], k["y"])])[0, 0] < W and 0 <= P.project(Htrue, [(k["x"], k["y"])])[0, 1] < H]
    ok("extract: landmarks pre-labelled through H(t)", len(rows[0]["landmarks"]) == len(vis) >= 6, f"{len(rows[0]['landmarks'])} vs {len(vis)}")
    ok("extract: nothing marked reviewed", not any(r["reviewed"] for r in rows))

    # ------------------------------------------------------------ QA on one frame
    errs, _ = R.check_frame(rows[0])
    ok("qa: pre-labelled player without team fails", any("needs team" in e for e in errs), str(errs))
    good = json.loads(json.dumps(rows[0]))
    good["boxes"][0]["team"] = "home"
    for m in good["landmarks"]:
        m["u"] += float(rng.normal(0, 0.5))
        m["v"] += float(rng.normal(0, 0.5))
    errs, info = R.check_frame(good)
    ok("qa: correct frame with 0.5 px click noise passes", not errs and info["rms_px"] < 1.0, f"{errs} {info.get('rms_px')}")
    bad = json.loads(json.dumps(good))
    bad["landmarks"][0]["u"] += 25
    errs, info = R.check_frame(bad)
    ok("qa: one landmark off by 25 px fails the 3 px RMS gate", any("RMS" in e for e in errs), f"{errs} {info.get('rms_px')}")

    def frame_with(**edit):
        f = json.loads(json.dumps(good))
        f.update(edit)
        return f

    cases = {
        "unknown class": frame_with(boxes=[{"cls": "coach", "x1": 1, "y1": 1, "x2": 9, "y2": 9}]),
        "box outside image": frame_with(boxes=[{"cls": "ball", "x1": 1270, "y1": 1, "x2": 1300, "y2": 9, "team": None}]),
        "inverted box": frame_with(boxes=[{"cls": "ball", "x1": 9, "y1": 9, "x2": 1, "y2": 1, "team": None}]),
        "referee with a team": frame_with(boxes=[{"cls": "referee", "x1": 1, "y1": 1, "x2": 9, "y2": 19, "team": "home"}]),
        "two balls": frame_with(boxes=[{"cls": "ball", "x1": 1, "y1": 1, "x2": 9, "y2": 9}, {"cls": "ball", "x1": 20, "y1": 1, "x2": 29, "y2": 9}]),
        "five landmarks": frame_with(landmarks=good["landmarks"][:5]),
        "unknown landmark id": frame_with(landmarks=good["landmarks"] + [{"id": "nope", "u": 1, "v": 1}]),
        "collinear pitch landmarks (left goal line)": frame_with(landmarks=[{"id": i, "u": 10.0 + 7 * k, "v": 100.0 + 90 * k + k * k}
            for k, i in enumerate(["c_lt", "pb_l_gt", "sb_l_gt", "sb_l_gb", "pb_l_gb", "c_lb"])]),
        "collinear image clicks (degenerate H, RMS 0)": frame_with(landmarks=[{"id": i, "u": float(u), "v": 64.6} for i, (u, v) in zip(
            ["c_lt", "h_t", "c_rt", "cc_t", "ctr", "cc_b"], P.project(Htrue, [P.xy(i) for i in ["c_lt", "h_t", "c_rt", "cc_t", "ctr", "cc_b"]]))]),
        "landmark outside the image": frame_with(landmarks=good["landmarks"][:-1] + [{**good["landmarks"][-1], "u": 1500.0}]),
    }
    for name, fr in cases.items():
        errs, _ = R.check_frame(fr)
        ok(f"qa: {name} is an error", bool(errs), name)
    ident = frame_with(boxes=[{"cls": "player", "x1": 1, "y1": 1, "x2": 9, "y2": 19, "team": "home", "id": 3},
                              {"cls": "player", "x1": 20, "y1": 1, "x2": 29, "y2": 19, "team": "away", "id": 3}])
    ok("qa: duplicate ids in an identity clip fail", any("duplicate ids" in e for e in R.check_frame(ident, identity=True)[0]))
    ident["boxes"][1]["id"] = None
    ok("qa: missing id in an identity clip fails", any("needs an id" in e for e in R.check_frame(ident, identity=True)[0]))

    # ------------------------------------------------------------ QA over the set
    for r in rows:
        for b in r["boxes"]:
            b["team"] = "home" if b["cls"] == "player" else None
    R.write_labels(out, rows)
    rep = R.qa(root)
    ok("qa: labels clean after teams are filled", rep["labels_ok"] and rep["errors"] == 0, json.dumps(rep["clips"][0]["errors"][:3]))
    ok("qa: 6 frames in 1 clip does not meet the size gate", not rep["size_ok"] and not rep["pass"])
    (out / rows[2]["image"]).write_bytes(b"tampered")
    ok("qa: an image changed after labelling is caught", R.qa(root)["errors"] >= 1)
    R.extract(video, "c1", "unit test render", "test", every_s=0.5, boxes=boxes, clip_json=sc, root=root)
    rows = R.read_labels(out)
    rows[1]["reviewed"] = True
    rows[1]["boxes"][0]["team"] = "away"
    R.write_labels(out, rows)
    R.extract(video, "c1", "unit test render", "test", every_s=0.5, boxes=boxes, clip_json=sc, root=root)
    again = R.read_labels(out)
    ok("extract: re-running keeps a reviewed frame's corrections", again[1]["reviewed"] and again[1]["boxes"][0]["team"] == "away")
    ok("extract: re-running resets unreviewed frames to pre-labels", again[0]["boxes"][0]["team"] is None)

    # ------------------------------------------------------------ leakage
    train = tmp / "train"
    (train / "a").mkdir(parents=True)
    other = cv2.resize(rng.integers(0, 255, (9, 16, 3), dtype=np.uint8), (W, H), interpolation=cv2.INTER_NEAREST)
    cv2.imwrite(str(train / "a" / "unrelated.jpg"), other)
    lk = R.leakage([train], root=root)
    ok("leakage: unrelated training image passes", lk["pass"] and lk["train_images"] == 1, json.dumps(lk))
    shutil.copy(out / again[3]["image"], train / "a" / "copy.jpg")
    img = cv2.imread(str(out / again[4]["image"]))
    cv2.imwrite(str(train / "a" / "reencoded.png"), cv2.resize(img, (1152, 648)))
    lk = R.leakage([train], root=root)
    ok("leakage: exact copy found by sha256", len(lk["exact"]) == 1, json.dumps(lk["exact"]))
    ok("leakage: re-encoded, resized copy found by dHash", len(lk["near"]) == 1, json.dumps(lk["near"]))

    # ------------------------------------------------------------ freeze / verify (thresholds lowered for the tiny set)
    shutil.rmtree(train / "a")
    R.MIN_FRAMES, R.MIN_CLIPS, R.MIN_IDENTITY_CLIPS = 1, 1, 0
    manifest = tmp / "MANIFEST.json"
    manifest.write_text((HUB / "eval" / "MANIFEST.json").read_text(encoding="utf-8"), encoding="utf-8")
    for r in again:
        for b in r["boxes"]:
            b["team"] = "home" if b["cls"] == "player" else None
    R.write_labels(out, again)
    try:
        R.freeze("tester", root=root, manifest=manifest, train_dirs=[train])
        ok("freeze: refuses while frames are unreviewed", False)
    except SystemExit as e:
        ok("freeze: refuses while frames are unreviewed", "not reviewed" in str(e), str(e))
    for r in again:
        r["reviewed"] = True
        for b in r["boxes"]:
            b["team"] = "home" if b["cls"] == "player" else None
    R.write_labels(out, again)
    nfiles = R.freeze("tester", root=root, manifest=manifest, train_dirs=[train])
    m = json.loads(manifest.read_text(encoding="utf-8"))
    ok("freeze: manifest records files, reviewer and date", m["frozen"] and nfiles == 8 and m["splits"]["real"]["reviewer"] == "tester"
       and m["splits"]["real"]["review_date"], f"{nfiles}")
    ok("freeze: files are read-only", not os.access(out / "labels.jsonl", os.W_OK))
    ok("verify: untouched set passes", R.verify(root, manifest)["pass"])
    lab = out / "labels.jsonl"
    os.chmod(lab, stat.S_IWRITE | stat.S_IREAD)
    lab.write_text(lab.read_text(encoding="utf-8").replace('"home"', '"away"', 1), encoding="utf-8")
    v = R.verify(root, manifest)
    ok("verify: an edited frozen label file fails", not v["pass"] and v["changed"] == ["c1/labels.jsonl"], json.dumps(v))
    (out / "frames" / "extra.jpg").write_bytes(b"x")
    ok("verify: an unrecorded file fails", "c1/frames/extra.jpg" in R.verify(root, manifest)["unrecorded"])
finally:
    for p in tmp.rglob("*"):
        try:
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
        except OSError:
            pass
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
