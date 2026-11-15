"""Galileo exam runner: prints every gate for a track and writes eval/results/<date>_<track>.json.

usage: python eval/run.py --track T0 [--browser PATH] [--skip-e2e]

Thresholds mirror GATES.md (frozen sections only). A gate that cannot be measured is a FAIL, never a skip,
unless --skip-e2e is passed, in which case the e2e gates are reported as NOT RUN and the track cannot pass.
"""

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HUB = Path(__file__).resolve().parents[1]
PY = sys.executable
RESULTS = HUB / "eval" / "results"
LOGS = RESULTS / "logs"

CLIP = HUB / "datasets/matches/metrica-sample-1/footage/synth-broadcast"
GT = HUB / "tests/e2e/out/broadcast/broadcast_gt.json"
TRACK_EVAL = HUB / "datasets/matches/video-synth-broadcast/eval.json"

# T0 baseline (AGENT_PROMPT.md section 2.3); tolerance 0.02 per GATES.md
# one-sided non-regression (GATES.md, amended 2026-11-13): +1 = higher is better, -1 = lower is better
T0_TRACKING = {"position_median_m": (0.16, -1), "recall_on_screen": (0.993, 1), "precision": (0.934, 1),
               "team_accuracy": (0.998, 1), "track_purity": (0.869, 1)}
T0_TOL = 0.02
# fragmentation as a count (GATES.md, amended 2026-11-15): <= 29 video tracks over exactly 19 provider players
T0_MAX_TRACKS, T0_PROVIDERS = 29, 19


def node_env():
    """The hub's js/ files are ES modules without a package.json; Node < 22 needs --experimental-detect-module."""
    env = dict(os.environ)
    node = shutil.which("node")
    if node:
        v = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v")
        if int(v.split(".")[0]) < 22:
            env["NODE_OPTIONS"] = (env.get("NODE_OPTIONS", "") + " --experimental-detect-module --no-warnings").strip()
    return env


def run(name, cmd, track):
    log = LOGS / f"{track}_{name}.log"
    r = subprocess.run(cmd, cwd=HUB, capture_output=True, text=True, env=node_env())
    log.write_text(r.stdout + r.stderr, encoding="utf-8")
    return r.returncode, r.stdout + r.stderr, str(log.relative_to(HUB)).replace("\\", "/")


def count(text, rx):
    m = re.findall(rx, text)
    return [tuple(int(x) for x in t) for t in m]


def find_browser(arg):
    for p in [arg, os.environ.get("CHROME"),
              r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              "/usr/bin/google-chrome"]:
        if p and Path(p).exists():
            return p
    return None


def gate(board, name, threshold, result, ok, evidence):
    board.append({"gate": name, "threshold": threshold, "result": result,
                  "status": "PASS" if ok is True else ("NOT RUN" if ok is None else "FAIL"), "evidence": evidence})


def t0(args):
    board, measured = [], {}
    # 1. Python toolkit (incl. Python <-> JS parity)
    rc, out, log = run("test_toolkit", [PY, "tests/py/test_toolkit.py"], "T0")
    c = count(out, r"(\d+) passed, (\d+) failed")
    p, f = c[-1] if c else (0, -1)
    gate(board, "test_toolkit", "33/33", f"{p}/{p + max(f, 0)}", rc == 0 and p == 33 and f == 0, log)
    # 2. JS unit tests
    tot_p = tot_f = 0
    logs = []
    for t in sorted((HUB / "tests/unit").glob("*.mjs")):
        rc, out, log = run(t.stem, ["node", str(t.relative_to(HUB))], "T0")
        c = count(out, r"(\d+) passed, (\d+) failed")
        p, f = c[-1] if c else (0, 1)
        tot_p, tot_f = tot_p + p, tot_f + (f if rc == 0 else max(f, 1))
        logs.append(log)
    gate(board, "unit (calib + shots + warp)", "77/77", f"{tot_p}/{tot_p + tot_f}", tot_p == 77 and tot_f == 0, ", ".join(logs))
    # 3. e2e suites in a real Chromium browser with H.264
    browser = find_browser(args.browser)
    for name, script, want in [("dataset_e2e", "tests/e2e/run_dataset_e2e.py", 19), ("footage_e2e", "tests/e2e/run_e2e.py", 14)]:
        if args.skip_e2e or not browser:
            gate(board, name, f"{want}/{want}", "not run" + ("" if browser else " (no Chrome/Edge found)"), None, "")
            continue
        rc, out, log = run(name, [PY, script, "--chrome", browser], "T0")
        c = count(out, r"(\d+)\s*/\s*(\d+) gates")
        p, n = c[-1] if c else (0, want)
        gate(board, name, f"{want}/{want}", f"{p}/{n}", rc == 0 and p == want and n == want, log)
    measured["browser"] = browser
    # 4. synthetic pipeline outputs
    if GT.exists() and (CLIP / "clip.json").exists():
        rc, out, log = run("score_keys", [PY, "tests/e2e/score_keys.py", str(CLIP / "clip.json"), str(GT)], "T0")
        keys = json.loads(out.strip().splitlines()[-1]) if rc == 0 else {}
        measured["keys"] = keys
        cuts = keys.get("cuts")
        gate(board, "synthetic cuts", "[8000, 10000] ms exact", cuts, cuts == [8000, 10000], log)
        rc, out, log = run("score_frames", [PY, "tests/e2e/score_frames.py", str(CLIP / "clip.json"), str(GT), "auto+flow"], "T0")
        measured["overlay"] = out.strip().splitlines()[-1] if out.strip() else None
    else:
        gate(board, "synthetic cuts", "[8000, 10000] ms exact", "pipeline not run", False, "")
    if TRACK_EVAL.exists():
        ev = json.loads(TRACK_EVAL.read_text())
        measured["tracking"] = ev
        for k, (base, sign) in T0_TRACKING.items():
            v = ev.get(k)
            limit = round(base - sign * T0_TOL, 6)
            ok = v is not None and sign * (float(v) - limit) >= -1e-9
            gate(board, f"synthetic tracking: {k}", f"{'>=' if sign > 0 else '<='} {limit}", v, ok,
                 str(TRACK_EVAL.relative_to(HUB)).replace("\\", "/"))
        tpp, seen = ev.get("tracks_per_player"), ev.get("provider_players_seen")
        n = round(float(tpp) * seen) if tpp is not None and seen else None
        gate(board, "synthetic tracking: video tracks", f"<= {T0_MAX_TRACKS} over {T0_PROVIDERS} players",
             f"{n} over {seen}", n is not None and seen == T0_PROVIDERS and n <= T0_MAX_TRACKS,
             str(TRACK_EVAL.relative_to(HUB)).replace("\\", "/") + ", logs/T0_fragmentation.log")
    else:
        gate(board, "synthetic tracking", "eval.json present", "missing", False, "")
    return board, measured


def t1(args):
    """T1 exam gates (GATES.md). eval/real must be built, reviewed by Keno and frozen with `eval/realset.py`."""
    sys.path.insert(0, str(HUB / "eval"))
    import realset as R
    board = []
    rc, out, log = run("test_eval", [PY, "tests/py/test_eval.py"], "T1")
    c = count(out, r"(\d+) passed, (\d+) failed")
    p, f = c[-1] if c else (0, 1)
    gate(board, "test_eval (exam tooling)", "all pass", f"{p}/{p + f}", rc == 0 and f == 0 and p > 0, log)
    rep = R.qa()
    (LOGS / "T1_qa.json").write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    ev = "eval/results/logs/T1_qa.json"
    gate(board, "eval/real size", f">= {R.MIN_FRAMES} frames, >= {R.MIN_CLIPS} clips",
         f"{rep['frames']} frames, {len(rep['clips'])} clips", rep["size_ok"], ev)
    gate(board, "identity clips", f">= {R.MIN_IDENTITY_CLIPS} clips of >= {R.MIN_IDENTITY_S:.0f} s",
         rep["identity_clips_ok"], rep["identity_ok"], ev)
    rms = [c["rms_px"]["max"] for c in rep["clips"] if c["rms_px"]]
    gate(board, "label QA", f"0 errors; clicked-H RMS < {R.MAX_LANDMARK_RMS_PX} px",
         f"{rep['errors']} errors, max RMS {max(rms) if rms else None}", rep["labels_ok"], ev)
    lk = R.leakage()
    (LOGS / "T1_leakage.json").write_text(json.dumps(lk, indent=2), encoding="utf-8")
    gate(board, "leakage (sha256 + dHash)", "0 matches", f"{len(lk['exact'])} exact, {len(lk['near'])} near "
         f"vs {lk['train_images']} training images", lk["pass"] and lk["eval_images"] > 0, "eval/results/logs/T1_leakage.json")
    m = json.loads((HUB / "eval/MANIFEST.json").read_text(encoding="utf-8"))
    real = m["splits"]["real"]
    complete = bool(real.get("files")) and all(all(f.get(k) for k in ("file", "sha256", "source", "licence", "split"))
                                               for f in real["files"])
    gate(board, "manifest complete", "every file: sha256, source, licence, split", f"{len(real.get('files', []))} files",
         complete, "eval/MANIFEST.json")
    gate(board, "Keno sign-off", "reviewer + date in manifest, every frame reviewed",
         f"{real.get('reviewer')} {real.get('review_date')}, reviewed {rep['reviewed']}/{rep['frames']}",
         bool(real.get("reviewer")) and bool(real.get("review_date")) and rep["all_reviewed"], "eval/MANIFEST.json")
    v = R.verify()
    gate(board, "frozen and unchanged", "frozen; 0 changed, 0 unrecorded files",
         f"frozen={v['frozen']}, {len(v['changed'])} changed, {len(v['unrecorded'])} unrecorded", v["pass"], "eval/MANIFEST.json")
    return board, {"qa": {k: rep[k] for k in ("frames", "reviewed", "errors", "classes", "teams")}}


TRACKS = {"T0": t0, "T1": t1}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--track", required=True, choices=sorted(TRACKS))
    ap.add_argument("--browser", default=None, help="Chrome or Edge executable for the e2e suites")
    ap.add_argument("--skip-e2e", action="store_true")
    args = ap.parse_args()
    LOGS.mkdir(parents=True, exist_ok=True)
    board, measured = TRACKS[args.track](args)
    w = max(len(g["gate"]) for g in board)
    for g in board:
        print(f"{g['status']:8} {g['gate']:<{w}}  {g['result']!s:<24} (threshold {g['threshold']})")
    passed = all(g["status"] == "PASS" for g in board)
    print(f"\n{args.track}: {'PASS' if passed else 'FAIL'} ({sum(g['status'] == 'PASS' for g in board)}/{len(board)} gates)")
    out = RESULTS / f"{dt.date.today().isoformat()}_{args.track}.json"
    out.write_text(json.dumps({"track": args.track, "date": dt.datetime.now().isoformat(timespec="seconds"),
                               "pass": passed, "gates": board, "measured": measured}, indent=2, default=str))
    print(f"wrote {out.relative_to(HUB)}")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
