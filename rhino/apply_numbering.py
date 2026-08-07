# -*- coding: utf-8 -*-
"""
Apply part numbering + machine-ready miter angles to Final::FinalCNCBoard1/2.

ADDITIVE ONLY. Creates four new sub-layers under "Final" and writes TextDots into
them. Nothing existing is modified; the GH definition is not touched.

Matching: each closed curve on a CNC board is a rigid (optionally mirrored) copy
of one flat outline in Final::FinalOutputFlat. Candidates come from
perimeter/area/radial-profile, then are VERIFIED by fitting the actual transform
and measuring max deviation. Only a fit under FIT_OK mm is called confirmed.

Angle convention (confirmed with Niklas):
  shown value = half the fold angle (90 = square, 45 = ordinary box corner)
  saw tilt    = 90 - shown          (0 on the scale = blade square to the face)
  tilt < 0    -> flip the piece over, set |tilt|
  |tilt| > 45 -> use the 45 deg jig, set |tilt| - 45

Mirroring: in the flat layout +Z is the panel's OUTER face. If the nest instance
is mirrored (transform determinant < 0) the piece lies outer-face-DOWN on the
board, so the flip instruction inverts. Handled per part.
"""
import Rhino
import Rhino.Geometry as rg
import System
import math
import re

execfile(r"C:\Users\nrahn\Documents\RhinoScripts\_np_helpers.py", globals())

FIT_OK     = 0.25
FIT_MAYBE  = 1.50
JIG_LIMIT  = 45.0
JIG_EPS    = 0.5
SQUARE_EPS = 0.5
REPORT     = r"C:\Users\nrahn\Documents\RhinoScripts\CutList_MiterAngles.txt"


def ensure_layer(name, parent_full, color):
    full = parent_full + "::" + name
    i = doc.Layers.FindByFullPath(full, -1)
    if i >= 0:
        for o in doc.Objects.FindByLayer(doc.Layers[i]):
            doc.Objects.Delete(o, True)
        return i
    p = doc.Layers.FindByFullPath(parent_full, -1)
    L = Rhino.DocObjects.Layer()
    L.Name = name
    L.Color = color
    if p >= 0:
        L.ParentLayerId = doc.Layers[p].Id
    return doc.Layers.Add(L)


def machine_setting(bevel, mirrored):
    """-> (setting_deg, flip, jig, label, true_tilt)"""
    tilt = 90.0 - bevel
    flip = tilt < -SQUARE_EPS
    if mirrored:
        flip = not flip
    a = abs(tilt)
    if a < SQUARE_EPS:
        return 0.0, False, False, "sq", 0.0
    jig = a > JIG_LIMIT + JIG_EPS
    setting = a - JIG_LIMIT if jig else a
    pre = ("F" if flip else "") + ("J" if jig else "")
    return setting, flip, jig, "%s%.0f" % (pre, setting), a


# --------------------------------------------------------------- gather
flats, angle_dots, orphan_dots = gather_flats()
boards = gather_boards()
mark_board_outline(boards)

# ------------------------------------------------------------- matching
pairs = []
for bi, b in enumerate(boards):
    if b["status"] == "BOARD OUTLINE":
        continue
    bp = profile(b["crv"])
    for fi, f in enumerate(flats):
        if abs(f["p"] - b["p"]) > 0.15 * max(f["p"], 1.0):
            continue
        if f["a"] > 0 and b["a"] > 0 and abs(f["a"] - b["a"]) > 0.30 * max(f["a"], 1.0):
            continue
        pairs.append((prof_dist(bp, f["prof"]), bi, fi))
pairs.sort()

for (score, bi, fi) in pairs:
    b, f = boards[bi], flats[fi]
    if b["m"] is not None or f["used"]:
        continue
    xf, dev = fit_transform(f["crv"], b["crv"])
    if xf is None or dev > FIT_MAYBE:
        continue
    b["m"], b["dev"], b["xf"] = f, dev, xf
    b["status"] = "CONFIRMED" if dev <= FIT_OK else "PROBABLE"
    f["used"] = True

# base plates were hand-edited after nesting (a notch was closed), so they never
# fit rigidly. Match them on size alone and mark them PROBABLE. They carry no
# bevels - every plate edge is square - so a transform is not needed.
plate_notes = []
for f in sorted([x for x in flats if not x["used"] and x["id"].startswith("BP")],
                key=lambda x: -x["p"]):
    best, bd = None, 1e18
    for b in boards:
        if b["m"] is not None or b["status"] == "BOARD OUTLINE":
            continue
        if f["a"] <= 0 or b["a"] <= 0:
            continue
        da = abs(b["a"] - f["a"]) / max(f["a"], 1.0)
        dp = abs(b["p"] - f["p"]) / max(f["p"], 1.0)
        if da > 0.10 or dp > 0.15:
            continue
        if da + dp < bd:
            bd, best = da + dp, b
    if best is not None:
        best["m"], best["dev"], best["xf"] = f, None, None
        best["status"] = "PROBABLE"
        f["used"] = True
        plate_notes.append("%s -> board curve area %.0f (%+.1f%% area, %+.1f%% perimeter) - "
                           "matched on size only, the outline was edited after nesting"
                           % (f["id"], best["a"], 100.0 * (best["a"] - f["a"]) / f["a"],
                              100.0 * (best["p"] - f["p"]) / f["p"]))

# ---------------------------------------------------------- write dots
parent = "Final"
lnum, lang = {}, {}
for bn in BOARDS:
    short = bn.split("::")[-1]
    lnum[bn] = ensure_layer(short + "Numbers", parent, System.Drawing.Color.Red)
    lang[bn] = ensure_layer(short + "Angles", parent, System.Drawing.Color.DarkGreen)

n_num = n_ang = n_mirror = 0
for b in boards:
    if b["status"] == "BOARD OUTLINE":
        continue
    an = Rhino.DocObjects.ObjectAttributes()
    an.LayerIndex = lnum[b["bn"]]
    ctr = centroid(b["crv"])
    if b["m"] is None:
        doc.Objects.AddTextDot(rg.TextDot("X", ctr), an)
        n_num += 1
        continue
    txt = b["m"]["id"] + ("" if b["status"] == "CONFIRMED" else "?")
    doc.Objects.AddTextDot(rg.TextDot(txt, ctr), an)
    n_num += 1
    if b["xf"] is None:
        continue
    mirrored = b["xf"].Determinant < 0
    b["mirrored"] = mirrored
    if mirrored:
        n_mirror += 1
    aa = Rhino.DocObjects.ObjectAttributes()
    aa.LayerIndex = lang[b["bn"]]
    for (pt, bev) in b["m"]["bev"]:
        q = rg.Point3d(pt)
        q.Transform(b["xf"])
        s, flip, jig, lab, tilt = machine_setting(bev, mirrored)
        doc.Objects.AddTextDot(rg.TextDot(lab, q), aa)
        n_ang += 1

doc.Views.Redraw()

# ------------------------------------------------------------- report
R = []
R.append("CUT LIST - miter angles, machine-ready")
R.append(doc.Path)
R.append("")
R.append("ANGLE CONVENTION")
R.append("  The number on the flat layout is HALF THE FOLD ANGLE:")
R.append("  90 = square edge, 45 = ordinary square building corner.")
R.append("")
R.append("      saw tilt = 90 - shown        (0 on your scale = blade square to the face)")
R.append("")
R.append("  so shown 65 -> set 25,  shown 45 -> set 45,  shown 135 -> flip and set 45.")
R.append("  tilt over 45 -> 45 deg JIG, set (tilt - 45).")
R.append("")
R.append("  Labels on the ...Angles layers:")
R.append("     25    set 25, piece as it lies on the board")
R.append("     F25   FLIP the piece over, then set 25")
R.append("     J7    45 deg JIG, then set 7   (true tilt 52)")
R.append("     FJ2   FLIP and JIG, set 2      (true tilt 47)")
R.append("     sq    square edge, no bevel")
R.append("")
R.append("  FLIP already accounts for parts the nest mirrored (%d of them): the flag is" % n_mirror)
R.append("  relative to the face that is UP as the part lies on the board.")
R.append("")
conf = len([b for b in boards if b["status"] == "CONFIRMED"])
prob = len([b for b in boards if b["status"] == "PROBABLE"])
unk = len([b for b in boards if b["status"] == "UNKNOWN"])
out = len([b for b in boards if b["status"] == "BOARD OUTLINE"])
R.append("MATCHING")
R.append("  board closed curves : %d  (confirmed %d, probable %d, unidentified %d, board outline %d)"
         % (len(boards), conf, prob, unk, out))
R.append("  flat parts          : %d  (found on a board: %d)"
         % (len(flats), len([f for f in flats if f["used"]])))
R.append("  number dots written : %d      angle dots written: %d" % (n_num, n_ang))
if plate_notes:
    R.append("")
    R.append("BASE PLATES (labelled with a trailing ?)")
    for p in plate_notes:
        R.append("  " + p)
R.append("")
missing = sorted([f["id"] for f in flats if not f["used"]])
R.append("*** PARTS NOT ON EITHER BOARD (%d) ***" % len(missing))
if missing:
    R.append("  %s" % ", ".join(missing))
    R.append("  These are in the final model but were never nested - they still have to be cut.")
R.append("")
R.append("UNIDENTIFIED BOARD CURVES (%d), marked X" % unk)
R.append("  Cut into the board but not one of the %d final parts - leftovers from an" % len(flats))
R.append("  earlier version. Do not use them.")
for b in boards:
    if b["status"] == "UNKNOWN":
        c = centroid(b["crv"])
        R.append("    %-6s area=%10.2f perim=%8.2f  at (%.1f, %.1f)"
                 % (b["bn"].split("::")[-1][-6:], b["a"], b["p"], c.X, c.Y))
R.append("")
R.append("=" * 74)
R.append("PER-PART CUT LIST")
R.append("=" * 74)
R.append("%-8s %-7s %-5s %6s %6s  %-6s %s" % ("part", "board", "mirr", "shown", "tilt", "set", "notes"))
njig = nflip = nedge = 0


def keyf(b):
    m = re.match(r'^(\d+)\.(\d+)', b["m"]["id"])
    return (0, int(m.group(1)), int(m.group(2))) if m else (1, 0, 0)


for b in sorted([x for x in boards if x["m"] is not None], key=keyf):
    bn = b["bn"].split("::")[-1][-6:]
    mirrored = b.get("mirrored", False)
    bevs = sorted(b["m"]["bev"], key=lambda z: -z[1])
    if not bevs:
        R.append("%-8s %-7s %-5s %6s %6s  %-6s %s"
                 % (b["m"]["id"], bn, "yes" if mirrored else "-", "-", "-", "-", "all edges square"))
        continue
    first = True
    for (pt, bev) in bevs:
        s, flip, jig, lab, tilt = machine_setting(bev, mirrored)
        note = []
        if flip:
            note.append("FLIP over")
            nflip += 1
        if jig:
            note.append("45 JIG")
            njig += 1
        nedge += 1
        R.append("%-8s %-7s %-5s %6.0f %6.0f  %-6s %s"
                 % (b["m"]["id"] if first else "", bn if first else "",
                    ("yes" if mirrored else "-") if first else "",
                    bev, tilt, lab, ", ".join(note)))
        first = False
R.append("")
R.append("SUMMARY: %d bevelled edges, %d need the jig, %d need the piece flipped." % (nedge, njig, nflip))

System.IO.File.WriteAllText(REPORT, "\r\n".join(R))

s = []
s.append("numbers=%d  angles=%d  mirrored parts=%d" % (n_num, n_ang, n_mirror))
s.append("confirmed=%d probable=%d unknown=%d outline=%d" % (conf, prob, unk, out))
s.append("parts not on a board (%d): %s" % (len(missing), ", ".join(missing)))
s.append("edges=%d jig=%d flip=%d" % (nedge, njig, nflip))
System.IO.File.WriteAllText(r"C:\Users\nrahn\Documents\RhinoScripts\_apply_summary.txt", "\n".join(s))
