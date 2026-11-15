"""Fragmentation diagnosis: for every provider player owned by 2+ video tracks, list the tracks, their frame
ranges and what lies between (gap length, frames the player was inside the camera view).
Same matching as video_track.evaluate (3 m gate, view polygon, replay clock), so the ratio equals tracks_per_player.

usage: python eval/diag_fragmentation.py [video_pack] [provider_pack]
"""
import json, sys
from collections import defaultdict
from pathlib import Path
import numpy as np
HUB = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(HUB / "tools"))
from galileo_data import video_track as VT
from galileo_data.pack import decode, replay_clock
from scipy.optimize import linear_sum_assignment
vpk = json.loads(Path(sys.argv[1] if len(sys.argv) > 1 else HUB / "datasets/matches/video-synth-broadcast/pack.ghp.json").read_text())
ppk = json.loads(Path(sys.argv[2] if len(sys.argv) > 2 else HUB / "datasets/matches/metrica-sample-1/pack.ghp.json").read_text())
v, p = decode(vpk), decode(ppk); rt = replay_clock(p)
votes = defaultdict(lambda: defaultdict(list)); inview = defaultdict(list)
for f in range(v["n"]):
    r = float(v["t"][f])
    if r < rt[0] - 0.1 or r > rt[-1] + 0.1: continue
    j = int(np.clip(np.searchsorted(rt, r), 1, len(rt) - 1))
    a = float(np.clip((r - rt[j-1]) / max(1e-6, rt[j] - rt[j-1]), 0, 1))
    pp = p["pos"][j-1] + (p["pos"][j] - p["pos"][j-1]) * a
    vx = VT.decode_view(vpk, f)
    if vx is None: continue
    pi = np.flatnonzero(VT.in_polygon(vx, np.nan_to_num(pp, nan=1e6)) & np.isfinite(pp[:, 0]))
    for q in pi: inview[q].append(f)
    von = np.flatnonzero(v["det"][f] >= 0); vi = von[VT.in_polygon(vx, v["pos"][f][von])] if len(von) else von
    if not len(pi) or not len(vi): continue
    C = np.sqrt(((v["pos"][f][vi][:, None] - pp[pi][None]) ** 2).sum(-1))
    rr, cc = linear_sum_assignment(np.where(C <= 3.0, C, 1e6))
    for a_, b_ in zip(rr, cc):
        if C[a_, b_] <= 3.0: votes[vi[a_]][pi[b_]].append(f)
owner = {vp: max(c, key=lambda k: len(c[k])) for vp, c in votes.items()}
frag = defaultdict(list)
for vp, pl in owner.items(): frag[pl].append(vp)
dt = float(v["t"][1] - v["t"][0])
print(f"frames {v['n']} dt {dt:.3f}s  provider players {len(frag)}  video tracks owning {sum(map(len, frag.values()))}  ratio {sum(map(len, frag.values()))/len(frag):.4f}")
for pl, vps in sorted(frag.items(), key=lambda x: -len(x[1])):
    if len(vps) < 2: continue
    segs = sorted((min(votes[vp][pl]), max(votes[vp][pl]), vp, len(votes[vp][pl])) for vp in vps)
    iv = set(inview[pl])
    desc = []
    for i, (a, b, vp, n) in enumerate(segs):
        desc.append(f"track {vp}: f{a}-{b} ({n} matched)")
        if i + 1 < len(segs):
            g0, g1 = b + 1, segs[i+1][0] - 1
            gap = list(range(g0, g1 + 1)); vis = sum(f in iv for f in gap)
            desc.append(f"gap {len(gap)*dt:.2f}s (in view {vis}/{len(gap)} frames)")
    print(f"provider {pl} ({p['players'][pl].get('team')}): " + " | ".join(desc))
