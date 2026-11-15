"""Round-trip tests for eval/cvat.py (labels.jsonl <-> CVAT for images 1.1). usage: python tests/py/test_cvat.py"""

import json
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

HUB = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HUB / "tools"))
sys.path.insert(0, str(HUB / "eval"))
import cvat as C  # noqa: E402
import realset as R  # noqa: E402

passed, failed = 0, 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print("FAIL:", name, detail)


rows = [
    {"image": "frames/000006.jpg", "sha256": "a" * 64, "frame": 6, "t_ms": 200, "size": [1920, 1080], "reviewed": False,
     "boxes": [{"cls": "player", "x1": 10.5, "y1": 20.25, "x2": 40.0, "y2": 90.0, "team": "home", "id": 7, "jersey": "10"},
               {"cls": "goalkeeper", "x1": 100, "y1": 100, "x2": 130, "y2": 180, "team": "away", "id": None, "jersey": None},
               {"cls": "referee", "x1": 300, "y1": 100, "x2": 330, "y2": 180, "team": None, "id": 3},
               {"cls": "ball", "x1": 500, "y1": 500, "x2": 508, "y2": 508, "team": None, "id": None}],
     "landmarks": [{"id": "ctr", "u": 960.0, "v": 540.0}, {"id": "cc_t", "u": 961.5, "v": 400.2}]},
    {"image": "frames/000011.jpg", "sha256": "b" * 64, "frame": 11, "t_ms": 400, "size": [1920, 1080], "reviewed": True,
     "boxes": [], "landmarks": [{"id": "h_t", "u": 900.0, "v": 200.0}]},
]

tmp = Path(tempfile.mkdtemp(prefix="galileo_cvat_"))
try:
    root = tmp / "real"
    d = root / "c1"
    d.mkdir(parents=True)
    (d / "clip.json").write_text(json.dumps({"source": "t", "licence": "t"}))
    R.write_labels(d, rows)

    xml = C.to_xml(rows)
    got = C.from_xml(ET.fromstring(xml))
    ok("round trip: same frames", set(got) == {"000006.jpg", "000011.jpg"})
    a, b = got["000006.jpg"], rows[0]
    ok("round trip: boxes identical", [{k: x.get(k) for k in ("cls", "x1", "y1", "x2", "y2", "team", "id")} for x in a["boxes"]]
       == [{k: x.get(k) for k in ("cls", "x1", "y1", "x2", "y2", "team", "id")} for x in b["boxes"]], json.dumps(a["boxes"]))
    ok("round trip: jersey kept, empty jersey -> None", a["boxes"][0]["jersey"] == "10" and a["boxes"][1]["jersey"] is None)
    ok("round trip: missing id survives as None (CVAT -1)", a["boxes"][1]["id"] is None and a["boxes"][2]["id"] == 3)
    ok("round trip: landmarks identical", a["landmarks"] == b["landmarks"], json.dumps(a["landmarks"]))
    ok("round trip: reviewed tag", got["000011.jpg"]["reviewed"] and not a["reviewed"])

    # a correction in CVAT: player becomes away, landmark dragged, frame marked reviewed
    e = ET.fromstring(xml)
    im = e.find("image[@name='000006.jpg']")
    im.find("box/attribute[@name='team']").text = "away"
    im.find("points").set("points", "970.00,545.00")
    ET.SubElement(im, "tag", label="reviewed", source="manual")
    zp = tmp / "export.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("annotations.xml", ET.tostring(e, encoding="unicode"))
    r = C.import_("c1", zp, root_dir=root)
    new = R.read_labels(d)
    ok("import: counts", r == {"frames": 2, "changed": 1, "reviewed": 2}, json.dumps(r))
    ok("import: team corrected", new[0]["boxes"][0]["team"] == "away")
    ok("import: landmark moved", new[0]["landmarks"][0] == {"id": "ctr", "u": 970.0, "v": 545.0})
    ok("import: sha256, frame, t_ms kept", new[0]["sha256"] == "a" * 64 and new[0]["frame"] == 6 and new[0]["t_ms"] == 200)
    ok("import: reviewed set", new[0]["reviewed"] and new[0]["prelabel"]["reviewed_in"] == "CVAT tag")

    # a partial export must not write anything
    e2 = ET.fromstring(xml)
    e2.remove(e2.find("image[@name='000011.jpg']"))
    (tmp / "partial.xml").write_text(ET.tostring(e2, encoding="unicode"))
    before = (d / "labels.jsonl").read_text()
    try:
        C.import_("c1", tmp / "partial.xml", root_dir=root)
        ok("import: partial export refused", False)
    except SystemExit as ex:
        ok("import: partial export refused", "missing" in str(ex) and (d / "labels.jsonl").read_text() == before, str(ex))
    # video-mode exports (tracks) are refused
    e3 = ET.fromstring(xml)
    ET.SubElement(e3, "track", id="0", label="player")
    (tmp / "tracks.xml").write_text(ET.tostring(e3, encoding="unicode"))
    try:
        C.import_("c1", tmp / "tracks.xml", root_dir=root)
        ok("import: track export refused", False)
    except SystemExit as ex:
        ok("import: track export refused", "tracks" in str(ex))
    # a completed job marks every frame reviewed, tags or not
    plain = tmp / "plain.xml"
    plain.write_text(C.to_xml([{**x, "reviewed": False} for x in rows]))
    r = C.import_("c1", plain, root_dir=root, job_completed=True)
    new = R.read_labels(d)
    ok("import: completed job -> all frames reviewed", r["reviewed"] == 2 and all(x["reviewed"] for x in new)
       and new[0]["prelabel"]["reviewed_in"] == "CVAT job completed", json.dumps(r))
    r = C.import_("c1", plain, root_dir=root)
    ok("import: open job without tags -> nothing reviewed", r["reviewed"] == 0, json.dumps(r))
    from cvat_sdk.api_client import models
    ok("job state: SDK OperationStatus('completed') counts as completed", C.job_is_completed(models.OperationStatus("completed"))
       and C.job_is_completed("completed") and not C.job_is_completed(models.OperationStatus("in progress")))
    spec = C.label_spec()
    ok("labels: 6 labels, 37 landmark ids", len(spec) == 6 and len(spec[4]["attributes"][0]["values"]) == 37)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
