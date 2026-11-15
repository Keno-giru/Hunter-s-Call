"""eval/real <-> CVAT (self-hosted) for Keno's review. Format: "CVAT for images 1.1" XML.

    python eval/cvat.py labels                       # writes eval/cvat/labels.json: paste into CVAT's Raw label editor
    python eval/cvat.py export [CLIP ...]            # eval/cvat/<clip>/annotations.xml (+ .zip) from labels.jsonl
    python eval/cvat.py import CLIP export.zip|.xml  # corrections back into eval/real/<clip>/labels.jsonl

Mapping (one CVAT task per clip, images = eval/real/<clip>/frames/*.jpg, matched by file name):
    box  player | goalkeeper   attributes team (home|away), id (-1 = none), jersey (text)
    box  referee               attribute id
    box  ball
    points landmark            attribute kp = pitch registry id (one point per landmark)
    tag  reviewed              image-level: Keno checked and corrected this frame

Import replaces boxes and landmarks of every frame present in the CVAT export, sets reviewed from the tag,
and keeps image, sha256, frame, t_ms and size. Frames missing from the export are an error (nothing is
written), so a partial export can never silently drop labels.
"""

import argparse
import io
import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

HUB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB / "tools"))
sys.path.insert(0, str(HUB / "eval"))
from galileo_data import pitch as P  # noqa: E402
import realset as R  # noqa: E402

OUT = HUB / "eval" / "cvat"
NO_ID = -1


def label_spec():
    """CVAT label constructor (Raw tab). Colours only help the eye."""
    team = {"name": "team", "mutable": False, "input_type": "select", "default_value": "home", "values": ["home", "away"]}
    tid = {"name": "id", "mutable": False, "input_type": "number", "default_value": str(NO_ID), "values": [str(NO_ID), "9999", "1"]}
    jersey = {"name": "jersey", "mutable": False, "input_type": "text", "default_value": "", "values": [""]}
    return [
        {"name": "player", "color": "#e5484d", "type": "rectangle", "attributes": [team, tid, jersey]},
        {"name": "goalkeeper", "color": "#f5a524", "type": "rectangle", "attributes": [team, tid, jersey]},
        {"name": "referee", "color": "#111111", "type": "rectangle", "attributes": [tid]},
        {"name": "ball", "color": "#ffffff", "type": "rectangle", "attributes": []},
        {"name": "landmark", "color": "#30a46c", "type": "points",
         "attributes": [{"name": "kp", "mutable": False, "input_type": "select", "default_value": P.IDS[0], "values": list(P.IDS)}]},
        {"name": "reviewed", "color": "#3e63dd", "type": "tag", "attributes": []},
    ]


# ---------------------------------------------------------------- export
def _attr(parent, name, value):
    a = ET.SubElement(parent, "attribute", name=name)
    a.text = "" if value is None else str(value)


def to_xml(rows):
    root = ET.Element("annotations")
    ET.SubElement(root, "version").text = "1.1"
    for i, r in enumerate(rows):
        w, h = r["size"]
        im = ET.SubElement(root, "image", id=str(i), name=Path(r["image"]).name, width=str(w), height=str(h))
        for b in r.get("boxes", []):
            e = ET.SubElement(im, "box", label=b["cls"], source="manual", occluded="0", z_order="0",
                              xtl=f"{b['x1']:.2f}", ytl=f"{b['y1']:.2f}", xbr=f"{b['x2']:.2f}", ybr=f"{b['y2']:.2f}")
            if b["cls"] in R.TEAMED:
                _attr(e, "team", b.get("team") or "home")
                _attr(e, "id", NO_ID if b.get("id") is None else b["id"])
                _attr(e, "jersey", b.get("jersey") or "")
            elif b["cls"] == "referee":
                _attr(e, "id", NO_ID if b.get("id") is None else b["id"])
        for m in r.get("landmarks", []):
            e = ET.SubElement(im, "points", label="landmark", source="manual", occluded="0", z_order="0",
                              points=f"{m['u']:.2f},{m['v']:.2f}")
            _attr(e, "kp", m["id"])
        if r.get("reviewed"):
            ET.SubElement(im, "tag", label="reviewed", source="manual")
    ET.indent(root)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def export(clip_ids=None):
    OUT.mkdir(parents=True, exist_ok=True)
    done = []
    for d in R.clips():
        if clip_ids and d.name not in clip_ids:
            continue
        rows = R.read_labels(d)
        names = [Path(r["image"]).name for r in rows]
        if len(set(names)) != len(names):
            raise SystemExit(f"{d.name}: duplicate image names; CVAT matches by name")
        o = OUT / d.name
        o.mkdir(parents=True, exist_ok=True)
        xml = to_xml(rows)
        (o / "annotations.xml").write_text(xml, encoding="utf-8")
        with zipfile.ZipFile(o / "annotations.zip", "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("annotations.xml", xml)
        done.append((d.name, len(rows)))
    return done


# ---------------------------------------------------------------- import
def _read_xml(path):
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if n.endswith("annotations.xml")), None)
            if name is None:
                raise SystemExit(f"{path}: no annotations.xml inside (export as 'CVAT for images 1.1')")
            return ET.parse(io.BytesIO(z.read(name))).getroot()
    return ET.parse(path).getroot()


def _attrs(e):
    return {a.get("name"): (a.text or "").strip() for a in e.findall("attribute")}


def _int_or_none(s):
    try:
        v = int(float(s))
    except (TypeError, ValueError):
        return None
    return None if v == NO_ID else v


def from_xml(root):
    """CVAT XML -> {image name: {"boxes", "landmarks", "reviewed"}}. Tracks (video mode) are refused."""
    if root.find("track") is not None:
        raise SystemExit("export contains tracks: use an image task (annotation mode) and export 'CVAT for images 1.1'")
    out = {}
    for im in root.findall("image"):
        boxes, lms = [], []
        for b in im.findall("box"):
            cls, a = b.get("label"), _attrs(b)
            box = {"cls": cls, "x1": round(float(b.get("xtl")), 2), "y1": round(float(b.get("ytl")), 2),
                   "x2": round(float(b.get("xbr")), 2), "y2": round(float(b.get("ybr")), 2), "team": None, "id": None}
            if cls in R.TEAMED:
                box["team"] = a.get("team") or None
                box["id"] = _int_or_none(a.get("id"))
                box["jersey"] = a.get("jersey") or None
            elif cls == "referee":
                box["id"] = _int_or_none(a.get("id"))
            boxes.append(box)
        for p in im.findall("points"):
            kp = _attrs(p).get("kp")
            for xy in (p.get("points") or "").split(";"):
                if xy.strip():
                    u, v = (float(x) for x in xy.split(","))
                    lms.append({"id": kp, "u": round(u, 1), "v": round(v, 1)})
        reviewed = any(t.get("label") == "reviewed" for t in im.findall("tag"))
        out[Path(im.get("name")).name] = {"boxes": boxes, "landmarks": lms, "reviewed": reviewed}
    return out


def import_(clip_id, path, root_dir=R.REAL):
    d = Path(root_dir) / clip_id
    rows = R.read_labels(d)
    if not rows:
        raise SystemExit(f"{clip_id}: no labels.jsonl")
    got = from_xml(_read_xml(path))
    names = {Path(r["image"]).name for r in rows}
    missing, extra = sorted(names - set(got)), sorted(set(got) - names)
    if missing or extra:
        raise SystemExit(f"{clip_id}: export does not match the clip: {len(missing)} frames missing "
                         f"{missing[:3]}, {len(extra)} unknown {extra[:3]}; nothing written")
    def norm(boxes, lms):          # compare values only: an absent key and a null value mean the same
        return json.dumps([[{k: v for k, v in b.items() if v is not None} for b in boxes], lms], sort_keys=True)

    changed = reviewed = 0
    for r in rows:
        g = got[Path(r["image"]).name]
        before = norm(r.get("boxes", []), r.get("landmarks", []))
        r["boxes"], r["landmarks"], r["reviewed"] = g["boxes"], g["landmarks"], g["reviewed"]
        changed += before != norm(r["boxes"], r["landmarks"])
        reviewed += r["reviewed"]
        if g["reviewed"]:
            r.setdefault("prelabel", {})["reviewed_in"] = "CVAT"
    R.write_labels(d, rows)
    return {"frames": len(rows), "changed": changed, "reviewed": reviewed}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("labels")
    e = sub.add_parser("export")
    e.add_argument("clips", nargs="*")
    i = sub.add_parser("import")
    i.add_argument("clip")
    i.add_argument("path")
    a = ap.parse_args()
    if a.cmd == "labels":
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "labels.json").write_text(json.dumps(label_spec(), indent=2), encoding="utf-8")
        print(f"wrote {(OUT / 'labels.json').relative_to(HUB)}: paste into Project > Labels > Raw")
    elif a.cmd == "export":
        for name, n in export(a.clips):
            print(f"{name}: {n} frames -> eval/cvat/{name}/annotations.zip")
    else:
        r = import_(a.clip, a.path)
        print(f"{a.clip}: {r['frames']} frames, {r['changed']} changed, {r['reviewed']} reviewed")
        rep = R.qa(only=a.clip)
        print("QA for this clip:", "PASS" if rep["labels_ok"] else f"{rep['errors']} errors (run realset.py qa --clip {a.clip})")


if __name__ == "__main__":
    main()
