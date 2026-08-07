# -*- coding: utf-8 -*-
"""
Export the Assembly Guide dataset  ->  assembly_data.js

Phase 1 of docs/AssemblyGuide_HANDOFF.md. READ-ONLY against the Rhino document
and against the Grasshopper definition: nothing is created, modified or deleted.

Run it with Rhino open, the .3dm loaded and the `miters` Grasshopper definition
solved, either through CodeListener or with _RunPythonScript.

WHY IT RE-RUNS THE COMPONENT
    The per-edge data the tool needs (bevel, mate, joint, and the segment
    geometry in both 3D and flat) lives in the component's internal `recs`
    records, which are never emitted - TB reports them as text but drops the
    geometry, and 27 edges are ABSORBED by their neighbours' miters during
    solving, so the edge list cannot be re-derived from the outlines either.
    So we read the component's own source and its live inputs and re-execute it
    in a private namespace. The bevel table and joint schedule we regenerate are
    then diffed against the component's live TB output; if they differ by one
    character the export aborts.

    The clash report is cut off the end before re-running - it is O(n^2)
    point-in-solid sampling and we already have its result from the live TB.

ANGLE CONVENTION (settled - do not re-derive, see README.md)
    shown = half the fold angle;  90 = square, 45 = ordinary box corner
    table = 90 - shown            (0 on the scale = square to the board face)
    table < 0   -> flip the piece over, set |table|
    |table| > 45 -> 45 deg jig, set |table| - 45
    Mirroring on the board inverts the flip flag.

    Settings are computed from the ROUNDED bevel, because that is the number
    printed on the flat layout and baked into the ...Angles layers, and §9.8 of
    the spec requires the tool to agree with those exactly.
"""

import Rhino
import Rhino.Geometry as rg
import Grasshopper as gh
import System
import math
import re

HELPERS = r"C:\Users\nrahn\Documents\RhinoScripts\_np_helpers.py"
CORE    = r"C:\Users\nrahn\Documents\RhinoScripts\_ag_core.py"
REPO    = r"C:\Users\nrahn\Documents\AssemblyGuide"
OUT_JS  = REPO + r"\assembly_data.js"
REPORT  = r"C:\Users\nrahn\Documents\RhinoScripts\_ag_verify.txt"

CLASH_MARKER = "clash report (buildability)"

SQUARE_EPS = 0.5
JIG_LIMIT  = 45.0
JIG_EPS    = 0.5
FIT_OK     = 0.25
FIT_MAYBE  = 1.50

UTF8 = System.Text.UTF8Encoding(False)     # no BOM - a BOM breaks `# coding:`

execfile(HELPERS, globals())               # doc, BOARDS, centroid, area_of, ...

RPT = []
def say(s):
    RPT.append(s)


# ------------------------------------------------------------ 1. the bridge

def vals(p):
    out = []
    d = p.VolatileData
    for i in range(d.PathCount):
        for it in d.get_Branch(d.get_Path(i)):
            out.append(it)
    return out


ghdoc = gh.Instances.ActiveCanvas.Document
if ghdoc is None:
    raise Exception("No Grasshopper document open - load the `miters` definition.")
comps = [o for o in ghdoc.Objects if o.GetType().Name == "ZuiPythonComponent"]
if len(comps) != 1:
    raise Exception("Expected exactly one Python component, found %d" % len(comps))
comp = comps[0]

Sp_in = [v.Value for v in vals(comp.Params.Input[0])]
Sb_in = [v.Value for v in vals(comp.Params.Input[1])]
T_in  = float(vals(comp.Params.Input[2])[0].Value)
M_in  = int(round(float(vals(comp.Params.Input[3])[0].Value)))
TB_live = [v.Value for v in vals(comp.Params.Output[6])]

if not Sp_in:
    raise Exception("Component input Sp is empty - is the definition solved?")

say("SOURCE")
say("  document      : %s" % doc.Path)
say("  GH inputs     : Sp=%d  Sb=%d  T=%.2f  M=%d" % (len(Sp_in), len(Sb_in), T_in, M_in))
say("  live TB lines : %d" % len(TB_live))


# --------------------------------------------- 2. re-run the component's code

code = comp.Code
cut = code.find(CLASH_MARKER)
if cut < 0:
    raise Exception("clash-report marker not found - the component source has changed")
cut = code.rfind("\n", 0, cut) + 1          # cut at the start of that comment line
System.IO.File.WriteAllText(CORE, code[:cut], UTF8)

ns = {"Sp": Sp_in, "Sb": Sb_in, "T": T_in, "M": M_in, "__name__": "__ag_core__"}
execfile(CORE, ns)

parts       = ns["parts"]
plate_parts = ns["plate_parts"]
layout      = ns["layout"]
P, B        = ns["P"], ns["B"]
fallbacks   = ns["fallbacks"]
joint_no    = ns["joint_no"]
TB_mine     = ns["TB"]

say("  re-run        : parts=%d plates=%d P=%d B=%d joints=%d fallbacks=%s"
    % (len(parts), len(plate_parts), len(P), len(B), len(joint_no), ",".join(fallbacks) or "-"))


# ------------------------------------------- 3. verify the re-run is faithful

def section(lines, head, stop):
    try:
        i = lines.index(head)
    except ValueError:
        return None
    out = []
    for L in lines[i + 1:]:
        if stop is not None and L.startswith(stop):
            break
        out.append(L)
    return out


BEV_H = "=== BEVEL TABLE ==="
JNT_H = "=== JOINT SCHEDULE (each shared edge once) ==="

bev_live = section(TB_live, BEV_H, "===")
bev_mine = section(TB_mine, BEV_H, "===")
jnt_live = section(TB_live, JNT_H, "===")
jnt_mine = section(TB_mine, JNT_H, "===")

say("")
say("FIDELITY CHECK  (regenerated vs the component's own live output)")
ok = True
for name, a, b in (("bevel table", bev_live, bev_mine), ("joint schedule", jnt_live, jnt_mine)):
    if a is None or b is None:
        say("  %-15s MISSING" % name)
        ok = False
        continue
    a = [x for x in a if x.strip()]
    b = [x for x in b if x.strip()]
    same = (a == b)
    say("  %-15s live=%-5d regenerated=%-5d  %s" % (name, len(a), len(b), "IDENTICAL" if same else "*** DIFFERS ***"))
    if not same:
        ok = False
        for i in range(min(len(a), len(b))):
            if a[i] != b[i]:
                say("      first difference at row %d" % i)
                say("        live: %s" % a[i])
                say("        mine: %s" % b[i])
                break
if not ok:
    System.IO.File.WriteAllText(REPORT, "\r\n".join(RPT), UTF8)
    raise Exception("Re-run does not reproduce the live component output - see " + REPORT)

# the bevel table minus its column header is the authoritative edge count
bev_rows = [r for r in bev_mine if r.strip() and not r.startswith("part,")]


# --------------------------------------------------- 4. the angle convention

def machine_setting(shown, mirrored):
    """shown = the rounded half-fold angle printed on the flat layout.
    -> (setting, flip, jig, label, true_tilt).  Identical to apply_numbering.py."""
    tilt = 90.0 - shown
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


# ------------------------------------------------------- 5. board matching
# Same procedure as apply_numbering.py, which produced the baked ...Numbers and
# ...Angles layers. Re-run rather than read the dots back, because the mirror
# flag is not baked and `flip` depends on it.

flats, angle_dots, orphan_dots = gather_flats()
boards = gather_boards()
mark_board_outline(boards)

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

# base plates were hand-edited after nesting so they never fit rigidly; match on
# size alone. Every plate edge is square, so no transform is needed.
plate_size_only = []
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
        plate_size_only.append((f["id"], 100.0 * (best["a"] - f["a"]) / f["a"]))

# id (normalised) -> board placement
board_of = {}
for b in boards:
    if b["m"] is None or b["status"] == "BOARD OUTLINE":
        continue
    pid_raw = b["m"]["id"]
    key = pid_raw.replace("*", "").replace("?", "")
    ctr = centroid(b["crv"])
    board_of[key] = {"sheet": b["bn"].split("::")[-1],
                     "x": ctr.X, "y": ctr.Y,
                     "mirrored": bool(b["xf"] is not None and b["xf"].Determinant < 0),
                     "exact": b["status"] == "CONFIRMED",
                     "crv": b["crv"]}

n_conf = len([b for b in boards if b["status"] == "CONFIRMED"])
n_prob = len([b for b in boards if b["status"] == "PROBABLE"])
n_unk  = len([b for b in boards if b["status"] == "UNKNOWN"])
n_out  = len([b for b in boards if b["status"] == "BOARD OUTLINE"])
n_mirr = len([v for v in board_of.values() if v["mirrored"]])

say("")
say("BOARD MATCHING")
say("  board curves  : %d  (confirmed %d, probable %d, leftover %d, sheet outline %d)"
    % (len(boards), n_conf, n_prob, n_unk, n_out))
say("  parts located : %d of %d      mirrored on the board: %d"
    % (len(board_of), len(flats), n_mirr))
say("  orphan angle dots: %d" % orphan_dots)


# ------------------------------------------------------------- 6. geometry

def poly_pts(c, tol=0.02):
    """Polyline points of a curve; curved spans are sampled."""
    ok, pl = c.TryGetPolyline()
    if ok and pl.Count > 1:
        return [pl[i] for i in range(pl.Count)]
    pts, segs = [], c.DuplicateSegments()
    if not segs:
        segs = [c]
    for s in segs:
        if s.IsLinear(tol):
            sub = [s.PointAtStart, s.PointAtEnd]
        else:
            n = max(4, int(math.ceil(s.GetLength() / 2.0)))
            sub = [s.PointAt(s.Domain.ParameterAt(i / float(n))) for i in range(n + 1)]
        if pts and pts[-1].DistanceTo(sub[0]) < 1e-7:
            sub = sub[1:]
        pts.extend(sub)
    return pts


def mesh_of(brep):
    mp = rg.MeshingParameters.FastRenderMesh
    mp.SimplePlanes = True
    ms = rg.Mesh.CreateFromBrep(brep, mp)
    m = rg.Mesh()
    if ms:
        for x in ms:
            m.Append(x)
    m.Faces.ConvertQuadsToTriangles()
    m.Compact()
    return m


def f2(x):
    s = "%.2f" % x
    if s.endswith(".00"):
        s = s[:-3]
    elif s.endswith("0"):
        s = s[:-1]
    return "0" if s in ("-0", "-0.0") else s


def f1(x):
    s = "%.1f" % x
    return s[:-2] if s.endswith(".0") else s


def js(s):
    out = []
    for ch in s:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ord(ch) < 0x20:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def a2(pts, mn=None):
    """[[x,y],...] 2 dp, optionally shifted so mn lands on the origin."""
    dx = mn.X if mn else 0.0
    dy = mn.Y if mn else 0.0
    return "[" + ",".join("[%s,%s]" % (f2(p.X - dx), f2(p.Y - dy)) for p in pts) + "]"


def a3(pts):
    return "[" + ",".join("[%s,%s,%s]" % (f2(p.X), f2(p.Y), f2(p.Z)) for p in pts) + "]"


# ------------------------------------------------------ 7. assemble the parts

by_joint = {}          # joint no -> [(partId, edgeIndex)]
part_rows = []         # parallel to `layout`
orphan_mates = []

tri_total = 0
vert_total = 0

for pi, p in enumerate(layout):
    is_plate = p["bi"] == 9999
    pid_s = p["id"]
    brep = B[pi - len(parts)] if is_plate else P[pi]
    mesh = mesh_of(brep)
    tri_total += mesh.Faces.Count
    vert_total += mesh.Vertices.Count

    xf = p["xform"]
    mn = p["min"]
    outline = poly_pts(p["fcurves"][0])
    outer_up = xf.Determinant > 0

    edges = []
    for i, r in enumerate(p["recs"]):
        shown = int(round(r["bevel"]))
        mirrored = board_of.get(pid_s, {}).get("mirrored", False)
        setting, flip, jig, label, tilt = machine_setting(shown, mirrored)
        seg = r["seg"]
        fseg = seg.DuplicateCurve()
        fseg.Transform(xf)
        j = r.get("joint", 0) or 0
        if j:
            by_joint.setdefault(j, []).append((pid_s, i))
        # "?" means the neighbouring face was skipped as a degenerate sliver, so
        # the edge is mitered against something that is not a part. Not a mate.
        mate = r.get("mate") or None
        if mate == "?":
            mate = None
            orphan_mates.append("%s e%d (%.2f mm)" % (pid_s, i, seg.GetLength()))
        edges.append({
            "n": i,
            "len": seg.GetLength(),
            "shown": shown,
            "set": setting,
            "flip": flip,
            "jig": jig,
            "label": label,
            "type": r["kind"],
            "needsWork": label != "sq",
            "mate": mate,
            "joint": j,
            "flatSeg": poly_pts(fseg),
            "seg3d": poly_pts(seg),
        })

    bb = brep.GetBoundingBox(True)
    part_rows.append({
        "id": pid_s, "building": ("BP" if is_plate else str(p["bi"] + 1)),
        "isPlate": is_plate, "area": p["area"], "mesh": mesh,
        "outline": outline, "min": mn, "outerUp": outer_up,
        "edges": edges, "bb": bb, "minZ": bb.Min.Z,
        "cz": brep.GetBoundingBox(True).Center.Z,
    })

# mateSet: the other half of each joint
row_of = dict((r["id"], r) for r in part_rows)
for j, members in by_joint.items():
    if len(members) < 2:
        continue
    for (pa, ea) in members:
        other = [(pb, eb) for (pb, eb) in members if pb != pa]
        if not other:
            continue
        pb, eb = other[0]
        row_of[pa]["edges"][ea]["mateSet"] = row_of[pb]["edges"][eb]["set"]
for r in part_rows:
    for e in r["edges"]:
        e.setdefault("mateSet", None)

n_edges = sum(len(r["edges"]) for r in part_rows)
n_work = sum(len([e for e in r["edges"] if e["needsWork"]]) for r in part_rows)
n_flip = sum(len([e for e in r["edges"] if e["flip"] and e["needsWork"]]) for r in part_rows)
n_jig = sum(len([e for e in r["edges"] if e["jig"]]) for r in part_rows)
n_45 = sum(len([e for e in r["edges"] if e["needsWork"] and abs(e["set"] - 45.0) < 0.01]) for r in part_rows)

say("")
say("EDGES")
say("  edge rows     : %d      (bevel table rows: %d)" % (n_edges, len(bev_rows)))
say("  needing work  : %d      already square as milled: %d" % (n_work, n_edges - n_work))
say("  flip / jig    : %d / %d      at the 45 setting: %d" % (n_flip, n_jig, n_45))
say("  distinct settings: %d"
    % len(set(round(e["set"], 0) for r in part_rows for e in r["edges"] if e["needsWork"])))
say("")
say("MESHES")
say("  triangles     : %d   vertices: %d   (avg %.0f tri/part)"
    % (tri_total, vert_total, tri_total / float(len(part_rows))))

# -------------------------------------------------- geometry currency check
# The board matching, and therefore `flip`, leans on the BAKED Final:: layers.
# Confirm those outlines are still the shapes the live definition produces - if
# they have drifted, the boards were milled from a different model and every
# board reference in this file would be a lie.
say("")
say("GEOMETRY CURRENCY  (baked Final::FinalOutputFlat vs the live solve)")
baked = {}
for f in flats:
    baked[f["id"].replace("*", "").replace("?", "")] = f
worst_p = worst_a = 0.0
worst_id = "-"
n_cmp = n_drift = 0
for pi, p in enumerate(layout):
    bk = baked.get(p["id"])
    if bk is None:
        continue
    live = p["fcurves"][0]
    dp = abs(live.GetLength() - bk["p"])
    da = abs(area_of(live) - bk["a"])
    n_cmp += 1
    if dp > 0.01 or da > 1.0:
        n_drift += 1
    if dp > worst_p:
        worst_p, worst_a, worst_id = dp, da, p["id"]
say("  outlines compared : %d      drifted: %d" % (n_cmp, n_drift))
say("  worst difference  : %s  perimeter %.4f mm, area %.3f mm2" % (worst_id, worst_p, worst_a))

# --------------------------------------------- staleness of the baked dots
# gather_flats() associates the baked angle TextDots with the flat outlines;
# apply_numbering.py used exactly that to write the board ...Angles layers. If
# the dot count per part does not match the live bevel table, the labels on the
# physical boards are incomplete.
want = {}
for r in part_rows:
    want[r["id"]] = len([e for e in r["edges"] if e["type"] != "square"])
got = {}
for f in flats:
    k = f["id"].replace("*", "").replace("?", "")
    got[k] = got.get(k, 0) + len(f["bev"])
stale = sorted([k for k in want if want[k] != got.get(k, 0)],
               key=lambda s: [int(x) for x in s.split(".")] if "." in s else [999])
say("")
say("BAKED ANGLE DOTS  (Final::FinalTextDots, the source of the board labels)")
say("  non-square edges live : %d" % sum(want.values()))
say("  angle dots baked      : %d" % sum(got.values()))
say("  parts where they disagree: %d" % len(stale))
for k in stale:
    say("    %-8s live %2d, baked %2d" % (k, want[k], got.get(k, 0)))


# ------------------------------------------------------------ 8. buildings

buildings = {}
for r in part_rows:
    if r["isPlate"]:
        continue
    buildings.setdefault(r["building"], []).append(r)

bld_rows = []
for bid in sorted(buildings.keys(), key=lambda s: int(s)):
    mem = buildings[bid]
    bb = rg.BoundingBox.Empty
    for r in mem:
        bb.Union(r["bb"])
    bld_rows.append({"id": bid, "parts": mem, "bb": bb})

say("")
say("BUILDINGS")
say("  count         : %d      parts each: %s"
    % (len(bld_rows), ", ".join(str(len(b["parts"])) for b in bld_rows)))


# ------------------------------------------------- 9. assembly order (spec 4)

adj = {}
for r in part_rows:
    adj[r["id"]] = set()
for r in part_rows:
    for e in r["edges"]:
        if e["mate"]:
            adj[r["id"]].add(e["mate"])
            adj.setdefault(e["mate"], set()).add(r["id"])

order = [r["id"] for r in part_rows if r["isPlate"]]
order_warn = []

for b in sorted(bld_rows, key=lambda b: (len(b["parts"]), int(b["id"]))):
    mem = b["parts"]
    zmin = min(r["minZ"] for r in mem)
    ground = [r for r in mem if r["minZ"] - zmin < 0.5]
    seed = max(ground or mem, key=lambda r: r["area"])
    placed = [seed]
    placed_ids = set([seed["id"]])
    rest = [r for r in mem if r["id"] != seed["id"]]
    while rest:
        def score(r):
            return (-len(adj[r["id"]] & placed_ids), r["cz"], -r["area"])
        rest.sort(key=score)
        nxt = rest.pop(0)
        if not (adj[nxt["id"]] & placed_ids):
            order_warn.append("building %s: %s joins nothing already placed" % (b["id"], nxt["id"]))
        placed.append(nxt)
        placed_ids.add(nxt["id"])
    order.extend(r["id"] for r in placed)

say("")
say("ASSEMBLY ORDER")
say("  sequenced     : %d of %d parts" % (len(order), len(part_rows)))
say("  parts placed with no joint to the already-placed set: %d" % len(order_warn))
for w in order_warn:
    say("    " + w)


# ----------------------------------------------------------- 10. board maps

board_maps = {}
for bn in BOARDS:
    short = bn.split("::")[-1]
    grp = [b for b in boards if b["bn"] == bn]
    # gather_boards() keeps only closed curves. The rest are real cuts too - on
    # board 1 the 850x850 sheet edge is drawn as two open polylines, which is
    # why that board has no closed sheet curve at all. Carry them all so the
    # board map is complete and the bbox is the actual sheet.
    marks = []
    bb = rg.BoundingBox.Empty
    n_obj = 0
    for o in lay_objs(bn):
        c = o.Geometry
        if not isinstance(c, rg.Curve):
            continue
        n_obj += 1
        bb.Union(c.GetBoundingBox(True))
        if not c.IsClosed:
            marks.append(poly_pts(c))
    sheet_area = (bb.Max.X - bb.Min.X) * (bb.Max.Y - bb.Min.Y)

    # _np_helpers.mark_board_outline() calls the largest closed curve the sheet
    # outline when it is 3x the next largest. On board 2 that promotes a 62 514
    # mm2 leftover - 11% of the sheet - and hides it from the "do not use these"
    # list. Decide on absolute size against the sheet instead.
    outs, left, sheet = [], [], None
    for b in grp:
        pts = poly_pts(b["crv"])
        if b["m"] is not None and b["status"] != "BOARD OUTLINE":
            outs.append((b["m"]["id"].replace("*", "").replace("?", ""), pts))
        elif b["a"] >= 0.80 * sheet_area:
            sheet = pts
        else:
            left.append(pts)

    board_maps[short] = {"bb": bb, "outlines": outs, "leftovers": left,
                         "sheet": sheet, "marks": marks}
    say("")
    say("BOARD %s" % short)
    say("  curves %d  ->  parts %d, closed leftovers %d, open marks %d, closed sheet outline %s"
        % (n_obj, len(outs), len(left), len(marks), "yes" if sheet else "no"))
    say("  sheet extent  : %.1f x %.1f mm" % (bb.Max.X - bb.Min.X, bb.Max.Y - bb.Min.Y))


# ------------------------------------------------------------ 11. warnings

not_nested = sorted([r["id"] for r in part_rows if r["id"] not in board_of],
                    key=lambda s: [int(x) for x in s.split(".")] if "." in s else [999])
warnings = []
if not_nested:
    warnings.append("Parts %s are not nested on either board and still have to be made."
                    % ", ".join(not_nested))
n_left = sum(len(v["leftovers"]) for v in board_maps.values())
if n_left:
    warnings.append("%d closed curves milled into the boards match no part - they are leftovers "
                    "from an earlier version of the model and are shown greyed out. Do not use "
                    "them." % n_left)
for (pid_s, dpct) in plate_size_only:
    warnings.append("%s was matched to its board curve on size alone (%+.1f%% area); the plate "
                    "outline was hand-edited after nesting. Every plate edge is square, so "
                    "nothing depends on the exact fit." % (pid_s, dpct))
for fb in fallbacks:
    warnings.append("Part %s is an unmitered fallback - a face too small to miter at T=%.1f. "
                    "Its edges are square; do not hunt for a bevel that is not there."
                    % (fb, T_in))
if stale:
    silent = [k for k in stale if got.get(k, 0) == 0 and want[k] > 0]
    msg = ("The angle labels drawn on the CNC boards are INCOMPLETE. They were written from a "
           "stale set of bevel dots (%d dots for %d bevelled edges), so %d parts carry fewer "
           "callouts on the board than they need: %s. Trust this tool, not the numbers on the "
           "board." % (sum(got.values()), sum(want.values()), len(stale), ", ".join(stale)))
    if silent:
        msg += (" Worst of all, %s show no bevel callout at all on the board and in fact need "
                "%s." % (" and ".join(silent), ", ".join("%d" % want[k] for k in silent)))
    warnings.append(msg)
if orphan_mates:
    warnings.append("These edges are mitered against a face too small to be a part, so they have "
                    "no mating piece to register against: %s. Sand the angle, but expect nothing "
                    "to meet it." % ", ".join(orphan_mates))
for L in TB_live:
    if "REAL CLASH" in L:
        warnings.append("Clash: %s - the model is thinner than 2*T there." % " ".join(L.split()))
for L in TB_live:
    if L.startswith("SKIPPED "):
        warnings.append(L.strip())
warnings.extend("Assembly order: " + w for w in order_warn)

say("")
say("WARNINGS (%d)" % len(warnings))
for w in warnings:
    say("  - " + w)


# --------------------------------------------------------------- 12. emit

O = []
O.append("// Generated by rhino/export_assembly_json.py - do not edit by hand.")
O.append("window.ASSEMBLY = {")

O.append('"meta":{"model":%s,"units":"mm","scale":"1:200","thickness":%s,'
         '"machine":"disc sander, tilting table, 0-45 plus a 45 deg jig",'
         '"angleConvention":"shown = half fold; table = 90 - shown; flip if negative; jig above 45",'
         '"generated":%s},'
         % (js(System.IO.Path.GetFileName(doc.Path)), f1(T_in),
            js(System.DateTime.Now.ToString("yyyy-MM-dd HH:mm"))))

b_out = []
for b in bld_rows:
    member_ids = [r["id"] for r in b["parts"]]
    ordered = [i for i in order if i in set(member_ids)]
    b_out.append('{"id":%s,"name":%s,"partIds":[%s],"bbox":[%s,%s,%s,%s,%s,%s]}'
                 % (js(b["id"]), js("Building " + b["id"]),
                    ",".join(js(i) for i in ordered),
                    f2(b["bb"].Min.X), f2(b["bb"].Min.Y), f2(b["bb"].Min.Z),
                    f2(b["bb"].Max.X), f2(b["bb"].Max.Y), f2(b["bb"].Max.Z)))
O.append('"buildings":[' + ",".join(b_out) + "],")


def mesh_js(m):
    v = []
    for i in range(m.Vertices.Count):
        p = m.Vertices[i]
        v.append("%s,%s,%s" % (f2(p.X), f2(p.Y), f2(p.Z)))
    t = []
    for i in range(m.Faces.Count):
        f = m.Faces[i]
        t.append("%d,%d,%d" % (f.A, f.B, f.C))
    return '{"v":[%s],"t":[%s]}' % (",".join(v), ",".join(t))


def edge_js(e, mn):
    fs = "[" + ",".join("[%s,%s]" % (f2(p.X - mn.X), f2(p.Y - mn.Y)) for p in e["flatSeg"]) + "]"
    return ('{"n":%d,"len":%s,"shown":%d,"set":%s,"flip":%s,"jig":%s,"label":%s,'
            '"type":%s,"needsWork":%s,"mate":%s,"mateSet":%s,"joint":%d,'
            '"flatSeg":%s,"seg3d":%s}'
            % (e["n"], f2(e["len"]), e["shown"], f1(e["set"]),
               "true" if e["flip"] else "false", "true" if e["jig"] else "false",
               js(e["label"]), js(e["type"]), "true" if e["needsWork"] else "false",
               js(e["mate"]) if e["mate"] else "null",
               f1(e["mateSet"]) if e["mateSet"] is not None else "null",
               e["joint"], fs, a3(e["seg3d"])))


p_out, pl_out = [], []
for r in part_rows:
    flags = []
    if r["id"] in fallbacks:
        flags.append("fallback")
    if r["id"] not in board_of:
        flags.append("notNested")
    bd = board_of.get(r["id"])
    if bd and not bd["exact"]:
        flags.append("sizeMatchOnly")
    board_js = ("null" if not bd else
                '{"sheet":%s,"x":%s,"y":%s,"mirrored":%s}'
                % (js(bd["sheet"]), f2(bd["x"]), f2(bd["y"]),
                   "true" if bd["mirrored"] else "false"))
    if r["isPlate"]:
        pl_out.append('{"id":%s,"area":%s,"mesh":%s,"flat":{"outline":%s,"outerFaceUp":%s},'
                      '"board":%s,"flags":[%s]}'
                      % (js(r["id"]), f2(r["area"]), mesh_js(r["mesh"]),
                         a2(r["outline"], r["min"]), "true" if r["outerUp"] else "false",
                         board_js, ",".join(js(f) for f in flags)))
        continue
    p_out.append('{"id":%s,"building":%s,"area":%s,"mesh":%s,'
                 '"flat":{"outline":%s,"outerFaceUp":%s},"edges":[%s],"board":%s,"flags":[%s]}'
                 % (js(r["id"]), js(r["building"]), f2(r["area"]), mesh_js(r["mesh"]),
                    a2(r["outline"], r["min"]), "true" if r["outerUp"] else "false",
                    ",".join(edge_js(e, r["min"]) for e in r["edges"]),
                    board_js, ",".join(js(f) for f in flags)))

O.append('"parts":[' + ",".join(p_out) + "],")
O.append('"plates":[' + ",".join(pl_out) + "],")

bm = []
for short in sorted(board_maps.keys()):
    v = board_maps[short]
    outs = ",".join('{"partId":%s,"pts":%s}' % (js(i), a2(pts)) for (i, pts) in v["outlines"])
    left = ",".join('{"pts":%s}' % a2(pts) for pts in v["leftovers"])
    marks = ",".join('{"pts":%s}' % a2(pts) for pts in v["marks"])
    bb = v["bb"]
    bm.append('%s:{"bbox":[%s,%s,%s,%s],"sheet":%s,"outlines":[%s],"leftovers":[%s],"marks":[%s]}'
              % (js(short), f2(bb.Min.X), f2(bb.Min.Y), f2(bb.Max.X), f2(bb.Max.Y),
                 (a2(v["sheet"]) if v["sheet"] else "null"), outs, left, marks))
O.append('"boardMaps":{' + ",".join(bm) + "},")

O.append('"order":[' + ",".join(js(i) for i in order) + "],")
O.append('"warnings":[' + ",".join(js(w) for w in warnings) + "]")
O.append("};")

blob = "\n".join(O)
System.IO.File.WriteAllText(OUT_JS, blob, UTF8)

say("")
say("OUTPUT")
say("  %s" % OUT_JS)
say("  %.1f KB" % (len(blob) / 1024.0))

System.IO.File.WriteAllText(REPORT, "\r\n".join(RPT), UTF8)
print("export done: %d parts, %d plates, %d edges, %.0f KB"
      % (len(p_out), len(pl_out), n_edges, len(blob) / 1024.0))
