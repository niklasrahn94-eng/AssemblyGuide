# -*- coding: utf-8 -*-
"""
MITER PANELS  v2  (exact per-edge setback construction)

Sp = miter pieces (building shell, open polysurface)   Sb = base plate(s), optional
T  = material thickness                                M  = 0 inward / 1 outward / 2 centered

Outputs
  P  = 3D mitered panels (closed solids)
  B  = base plate solid(s), thickened DOWN, cutouts preserved
  A  = part-ID TextDots on the 3D panels
  FL = flat cut outlines, shelf-packed per building on world XY
  BV = bevel TextDots + part labels on the flat layout
  TB = text report: bevel table + joint schedule + warnings

WHY v2:  v1 mitered by trimming each slab with an INFINITE bisector plane
(Brep.Trim).  On any face that is not convex, that plane also slices through
distant parts of the same panel -> up to 94% of the panel destroyed.  v1 also
dropped every face that was not planar within doc tolerance.

v2 instead builds the panel directly:
  outer outline (on the face plane, at height h_out along n)
  inner outline (at h_in) = each edge offset in-plane by its own setback
      a(h) = -h * (n . m) / (inA . m)          m = unit normal of the bisector plane
  side walls = ruled surface per edge between the two outlines.
No booleans, no infinite trims, exact for lines and arcs, sign-correct for
convex AND reentrant corners.  If a panel still fails to close, it falls back
to an unmitered slab and is REPORTED - a piece is never silently dropped.
"""

import Rhino
import Rhino.Geometry as rg
import System
from System.Collections.Generic import List
import math

DOC  = Rhino.RhinoDoc.ActiveDoc
TOL  = DOC.ModelAbsoluteTolerance

PLANE_TOLS    = [TOL, 0.01, 0.05, 0.1, 0.5, 2.0]  # ladder for TryGetPlane
MIN_AREA      = 0.5      # mm^2 - below this a face is junk, skipped + reported
GROUND_DEG    = 15.0     # face within this of horizontal counts as ground
SETBACK_CLAMP = 6.0      # max |setback| as a multiple of T
FIT           = 0.01     # curve/point comparison tolerance
NO_CORNER     = getattr(rg.CurveOffsetCornerStyle, "None")


# ----------------------------------------------------------------- helpers

def _list(x):
    if x is None:
        return []
    try:
        return [i for i in x]
    except:
        return [x]


def netlist(t, items):
    L = List[t]()
    for i in items:
        if i is not None:
            L.Add(i)
    return L


def face_plane(f):
    """Outward-oriented plane of a face. Walks a tolerance ladder, then falls
    back to a least-squares fit. Returns (plane, tol_used) - tol_used is None
    when the plane came from a fit."""
    for t in PLANE_TOLS:
        ok, pl = f.TryGetPlane(t)
        if ok:
            n = pl.Normal
            if f.OrientationIsReversed:
                n = -n
            return rg.Plane(pl.Origin, n), t
    pts = []
    for lp in f.Loops:
        c = lp.To3dCurve()
        if c is None:
            continue
        for i in range(21):
            pts.append(c.PointAt(c.Domain.ParameterAt(i / 20.0)))
    if len(pts) < 3:
        return None, None
    rc, pl = rg.Plane.FitPlaneToPoints(pts)
    if rc == rg.PlaneFitResult.Failure:
        return None, None
    n = pl.Normal
    sn = f.NormalAt(f.Domain(0).Mid, f.Domain(1).Mid)
    if f.OrientationIsReversed:
        sn = -sn
    if n * sn < 0:
        n = -n
    return rg.Plane(pl.Origin, n), None


def flatten(seg, plane):
    """Project a segment onto the plane only if it actually deviates."""
    dev = 0.0
    for i in range(5):
        p = seg.PointAt(seg.Domain.ParameterAt(i / 4.0))
        dev = max(dev, abs(plane.DistanceTo(p)))
    if dev <= max(TOL, 1e-4):
        return seg
    pr = rg.Curve.ProjectToPlane(seg, plane)
    return pr if pr else seg


def loop_segments(f, lp):
    """Ordered [(segment, edge_index)] following the loop travel direction."""
    c3 = lp.To3dCurve()
    if c3 is None:
        return []
    segs = c3.DuplicateSegments()
    if segs is None or len(segs) == 0:
        segs = [c3]
    edges = []
    for ti in range(lp.Trims.Count):
        tr = lp.Trims[ti]
        if tr.TrimType == rg.BrepTrimType.Singular:
            continue
        if tr.Edge is not None:
            edges.append(tr.Edge)
    out = []
    for s in segs:
        if s.GetLength() < TOL:
            continue
        mid = s.PointAtNormalizedLength(0.5)
        best, bd = -1, 1e18
        for e in edges:
            rc, t = e.EdgeCurve.ClosestPoint(mid)
            if rc:
                d = e.EdgeCurve.PointAt(t).DistanceTo(mid)
                if d < bd:
                    bd, best = d, e.EdgeIndex
        out.append((s, best if bd < max(0.1, TOL * 100) else -1))
    return out


def inward_dir(f, nrm, Pm, d, scale):
    """Unit vector in the face plane, perpendicular to d, pointing into the
    face material. Point-membership test is authoritative; loop orientation
    is the fallback."""
    v = rg.Vector3d.CrossProduct(nrm, d)
    if v.Length < 1e-12:
        return None
    v.Unitize()
    eps = max(min(scale * 0.25, 0.5), 1e-3)
    for mul in (1.0, 0.25, 0.05, 0.01):
        for cand in (v, -v):
            p = Pm + cand * (eps * mul)
            rc, u, vv = f.ClosestPoint(p)
            if rc and f.IsPointOnFace(u, vv) == rg.PointFaceRelation.Interior:
                return cand
    sn = -nrm if f.OrientationIsReversed else nrm
    w = rg.Vector3d.CrossProduct(sn, d)
    if w.Length < 1e-12:
        return None
    w.Unitize()
    return w


def seg_offset(seg, a, inA, nrm):
    """Offset one segment inside the face plane by signed distance a along inA.
    Exact for lines and arcs."""
    if abs(a) < 1e-9:
        return seg.DuplicateCurve()
    if seg.IsLinear(FIT):
        c = seg.DuplicateCurve()
        c.Translate(inA * a)
        return c
    ok, arc = seg.TryGetArc(FIT)
    if ok:
        rad = seg.PointAtNormalizedLength(0.5) - arc.Center
        rad.Unitize()
        sgn = 1.0 if (rad * inA) > 0 else -1.0
        nr = arc.Radius + sgn * a
        if nr <= FIT:
            return None
        return rg.ArcCurve(rg.Arc(arc.Plane, nr, arc.Angle))
    pl = rg.Plane(seg.PointAtStart, nrm)
    tgt = seg.PointAtNormalizedLength(0.5) + inA * a
    best, bd = None, 1e18
    for dd in (a, -a):
        try:
            res = seg.Offset(pl, dd, FIT, NO_CORNER)
        except:
            res = None
        if res:
            for rc in res:
                dist = rc.PointAtNormalizedLength(0.5).DistanceTo(tgt)
                if dist < bd:
                    bd, best = dist, rc
    if best is not None:
        return best
    c = seg.DuplicateCurve()
    c.Translate(inA * a)
    return c


def extend(c, amount):
    """Extend both ends. An arc is never extended past ~340 deg of total sweep -
    beyond that the extension wraps onto itself and the curve parameters stop
    being monotonic, which silently inverts every later Trim."""
    ok, arc = c.TryGetArc(FIT)
    if ok and arc.Radius > 1e-9:
        room = (math.radians(340.0) - abs(arc.Angle)) * arc.Radius * 0.5
        if room <= FIT:
            return c.DuplicateCurve()
        amount = min(amount, room)
    try:
        style = rg.CurveExtensionStyle.Line if c.IsLinear(FIT) else rg.CurveExtensionStyle.Arc
        e = c.Extend(rg.CurveEnd.Both, amount, style)
        if e:
            return e
    except:
        pass
    try:
        e = c.Extend(rg.CurveEnd.Both, amount, rg.CurveExtensionStyle.Smooth)
        if e:
            return e
    except:
        pass
    return c.DuplicateCurve()


def corner_solve(offs, ext, orig_corners, limits):
    """For each corner i (between offs[i] and offs[i+1]) return
    (t_end_on_ext_i, t_start_on_ext_j) or None if the corner opens up.
    A hit further from the original corner than limits[i] is rejected - that is
    a spurious intersection of the extensions, not the real corner."""
    n = len(offs)
    hits = []
    for i in range(n):
        j = (i + 1) % n
        a, b = offs[i], offs[j]
        # 1. endpoints already coincide (setback 0, or a genuinely shared vertex)
        if a.PointAtEnd.DistanceTo(b.PointAtStart) <= FIT:
            ra, ta = ext[i].ClosestPoint(a.PointAtEnd)
            rb, tb = ext[j].ClosestPoint(b.PointAtStart)
            hits.append((ta, tb) if (ra and rb) else None)
            continue
        # 2. intersect the extended offsets, take the hit nearest the old corner
        best, bd = None, 1e18
        try:
            ev = rg.Intersect.Intersection.CurveCurve(ext[i], ext[j], FIT, FIT)
        except:
            ev = None
        if ev:
            for k in range(ev.Count):
                x = ev[k]
                if x.IsOverlap:
                    continue
                dist = x.PointA.DistanceTo(orig_corners[i])
                if dist < bd:
                    bd, best = dist, (x.ParameterA, x.ParameterB)
        hits.append(best if (best is not None and bd <= limits[i]) else None)
    return hits


def build_pieces(offs, ext, hits, closed):
    """Trim each extended offset back to its two corner parameters.
    Returns (pieces, -1) or (None, index_of_the_segment_that_collapsed)."""
    n = len(offs)
    out = []
    for i in range(n):
        pi = (i - 1) % n
        c = ext[i]
        if closed[pi] and hits[pi] is not None:
            t0 = hits[pi][1]
        else:
            rc, t0 = c.ClosestPoint(offs[i].PointAtStart)
            if not rc:
                return None, i
        if closed[i] and hits[i] is not None:
            t1 = hits[i][0]
        else:
            rc, t1 = c.ClosestPoint(offs[i].PointAtEnd)
            if not rc:
                return None, i
        if t1 - t0 <= 1e-9:
            return None, i       # segment consumed by its neighbours' setbacks
        sub = c.Trim(t0, t1)
        if sub is None or sub.GetLength() < 1e-9:
            return None, i
        out.append(sub)
    return out, -1


def solve_loop(recs, nrm, T, h_out, h_in, label, dropped):
    """Resolve one loop into (kept_recs, closed_flags, outer_pieces, inner_pieces).
    A segment too short to survive its neighbours' setbacks is dropped and the
    loop is re-solved, rather than failing the whole panel."""
    keep = list(range(len(recs)))
    for _ in range(len(recs) + 1):
        if len(keep) < 3:
            return None
        sub = [recs[i] for i in keep]
        nseg = len(sub)
        orig_corners = [sub[i]["seg"].PointAtEnd for i in range(nseg)]
        maxlen = max(r["seg"].GetLength() for r in sub)
        ext_len = max(8.0 * T, 0.3 * maxlen, 5.0)
        lvl = {}
        for tag, key, h in (("out", "a_out", h_out), ("in", "a_in", h_in)):
            offs = []
            for r in sub:
                o = seg_offset(r["seg"], r[key], r["inA"], nrm)
                if o is None:
                    return None
                offs.append(o)
            if abs(h) > 1e-12:
                for o in offs:
                    o.Translate(nrm * h)
            corners = [c + nrm * h for c in orig_corners]
            ext = [extend(o, ext_len) for o in offs]
            limits = []
            for i in range(nseg):
                j = (i + 1) % nseg
                limits.append(3.0 * (abs(sub[i][key]) + abs(sub[j][key])) + 4.0 * T
                              + 0.5 * (sub[i]["seg"].GetLength() + sub[j]["seg"].GetLength()))
            lvl[tag] = (offs, ext, corner_solve(offs, ext, corners, limits))

        closed = [(lvl["out"][2][i] is not None) and (lvl["in"][2][i] is not None)
                  for i in range(nseg)]
        po, bo = build_pieces(lvl["out"][0], lvl["out"][1], lvl["out"][2], closed)
        pin, bin_ = build_pieces(lvl["in"][0], lvl["in"][1], lvl["in"][2], closed)
        if po is not None and pin is not None:
            return sub, closed, po, pin
        drop = bo if bo >= 0 else bin_
        if drop < 0:
            return None
        dropped.append("%s: edge %d (%.2f mm) absorbed by the miters either side at T=%.1f"
                       % (label, keep[drop], recs[keep[drop]]["seg"].GetLength(), T))
        keep.pop(drop)
    return None


def assemble(pieces, closed):
    """Interleave pieces with bridge lines at open corners. The ordering is
    identical for the outer and inner outline, so walls pair up 1:1."""
    n = len(pieces)
    crvs, kinds = [], []
    for i in range(n):
        crvs.append(pieces[i])
        kinds.append("p")
        if not closed[i]:
            a = pieces[i].PointAtEnd
            b = pieces[(i + 1) % n].PointAtStart
            crvs.append(rg.LineCurve(a, b))
            kinds.append("b")
    return crvs, kinds


def close_curve(crvs):
    live = netlist(rg.Curve, [c for c in crvs if c.GetLength() > FIT * 0.5])
    if live.Count == 0:
        return None
    j = rg.Curve.JoinCurves(live, max(FIT, TOL * 10))
    if not j or len(j) != 1:
        return None
    c = j[0]
    if not c.IsClosed:
        if not c.MakeClosed(max(FIT, TOL * 10)):
            return None
    return c


# ----------------------------------------------------------------- inputs

Sp_l = _list(Sp)
Sb_l = _list(Sb)
try:
    T = float(T)
except:
    T = 4.0
if T <= 0:
    T = 4.0
try:
    M = int(round(float(M)))
except:
    M = 0
if M not in (0, 1, 2):
    M = 0

H_OUT, H_IN = {0: (0.0, -T), 1: (T, 0.0), 2: (T / 2.0, -T / 2.0)}[M]

ground_dot = math.cos(math.radians(GROUND_DEG))
have_plate = len([b for b in Sb_l if isinstance(b, rg.Brep)]) > 0

warn = []
skipped = []


# --------------------------------------------------- collect the face table

faces = []          # (brep_idx, brep, face_idx, plane, area, plane_tol)
for bi, brep in enumerate(Sp_l):
    if not isinstance(brep, rg.Brep):
        warn.append("Sp[%d] is not a Brep (%s) - set the input TypeHint to Brep" % (bi, type(brep).__name__))
        continue
    for fi in range(brep.Faces.Count):
        f = brep.Faces[fi]
        pl, ptol = face_plane(f)
        if pl is None:
            skipped.append("Sp[%d].F%d  no plane could be fitted" % (bi, fi))
            continue
        amp = rg.AreaMassProperties.Compute(f.DuplicateFace(False))
        area = amp.Area if amp else 0.0
        if area < MIN_AREA:
            skipped.append("Sp[%d].F%d  area %.3f < %.2f (degenerate sliver)" % (bi, fi, area, MIN_AREA))
            continue
        if (not have_plate) and abs(pl.Normal * rg.Vector3d.ZAxis) >= ground_dot:
            continue                                    # auto-detected ground -> goes to B
        if ptol is None:
            warn.append("Sp[%d].F%d  NOT planar - flattened onto a best-fit plane" % (bi, fi))
        elif ptol > TOL:
            warn.append("Sp[%d].F%d  planar only within %.3f - flattened" % (bi, fi, ptol))
        faces.append((bi, brep, fi, pl, area, ptol))

face_plane_cache = {}
for (bi, brep, fi, pl, area, ptol) in faces:
    face_plane_cache[(bi, fi)] = pl


def neighbour_plane(bi, brep, fj):
    key = (bi, fj)
    if key in face_plane_cache:
        return face_plane_cache[key]
    pl, _ = face_plane(brep.Faces[fj])
    face_plane_cache[key] = pl
    return pl


# --------------------------------------------------------- build the panels

# part id per (bi, fi)
pid = {}
counter = {}
for (bi, brep, fi, pl, area, ptol) in faces:
    counter[bi] = counter.get(bi, 0) + 1
    pid[(bi, fi)] = "%d.%d" % (bi + 1, counter[bi])

joint_no = {}
joint_rows = []

P, A = [], []
parts = []      # dict per part, feeds the flat layout
fallbacks = []
dropped = []    # edges too short to survive their own miters

for (bi, brep, fi, plane, area, ptol) in faces:
    f = brep.Faces[fi]
    n = plane.Normal
    me = pid[(bi, fi)]
    scale = math.sqrt(max(area, 1.0))

    loops = []          # per loop: list of segment records
    ok_face = True

    for lp in f.Loops:
        if lp.LoopType not in (rg.BrepLoopType.Outer, rg.BrepLoopType.Inner):
            continue
        recs = []
        for (seg0, ei) in loop_segments(f, lp):
            seg = flatten(seg0, plane)
            mid = seg.PointAtNormalizedLength(0.5)
            d = seg.TangentAt(seg.Domain.ParameterAt(0.5))
            if d.Length < 1e-12:
                ok_face = False
                break
            d.Unitize()
            inA = inward_dir(f, n, mid, d, scale)
            if inA is None:
                ok_face = False
                break

            bevel, fold, shift, kind, mate = 90.0, 180.0, 0.0, "square", ""
            a_out, a_in = 0.0, 0.0

            if ei >= 0:
                e = brep.Edges[ei]
                if e.Valence == rg.EdgeAdjacency.Interior:
                    adj = list(e.AdjacentFaces())
                    fj = adj[0] if adj[1] == fi else adj[1]
                    pl_b = neighbour_plane(bi, brep, fj)
                    if pl_b is not None:
                        inB = inward_dir(brep.Faces[fj], pl_b.Normal, mid, d, scale)
                        if inB is not None:
                            bis = inA + inB
                            if bis.Length > 1e-7:
                                bis.Unitize()
                                m = rg.Vector3d.CrossProduct(d, bis)
                                if m.Length > 1e-12:
                                    m.Unitize()
                                    den = inA * m
                                    if abs(den) > 1e-7:
                                        num = n * m
                                        a_out = -H_OUT * num / den
                                        a_in = -H_IN * num / den
                                        lim = SETBACK_CLAMP * T
                                        if abs(a_out) > lim or abs(a_in) > lim:
                                            warn.append("%s edge %d: setback clamped (fold near 0/360)" % (me, len(recs)))
                                            a_out = max(-lim, min(lim, a_out))
                                            a_in = max(-lim, min(lim, a_in))
                                        shift = a_in - a_out
                                        bevel = math.degrees(math.atan2(T, shift))
                                        fold = 2.0 * bevel
                                        kind = "miter" if abs(shift) > FIT else "flat"
                                        key = (bi, ei)
                                        if key not in joint_no:
                                            joint_no[key] = len(joint_no) + 1
                                        mate = pid.get((bi, fj), "?")
                                        if kind == "miter" and fi < fj:
                                            joint_rows.append("J%-4d %-8s <-> %-8s  fold %6.1f  bevel %5.1f  len %7.2f"
                                                              % (joint_no[key], me, mate, fold, bevel, e.GetLength()))
            recs.append({"seg": seg, "inA": inA, "a_out": a_out, "a_in": a_in,
                         "bevel": bevel, "fold": fold, "shift": shift,
                         "kind": kind, "mate": mate,
                         "joint": joint_no.get((bi, ei), 0) if ei >= 0 else 0})
        if not ok_face or len(recs) < 3:
            if len(recs) < 3:
                ok_face = False
            break
        loops.append((lp.LoopType, recs))

    solid = None
    outer_flat = None
    kept_recs = None

    if ok_face and len(loops) > 0:
        try:
            out_sets, in_sets, wall_pairs = [], [], []
            kept_recs = []
            for (ltype, recs) in loops:
                res = solve_loop(recs, n, T, H_OUT, H_IN, me, dropped)
                if res is None:
                    raise ValueError("outline could not be resolved")
                sub, closed, po, pi_ = res
                kept_recs.extend(sub)

                co, ko = assemble(po, closed)
                ci, ki = assemble(pi_, closed)
                cco = close_curve(co)
                cci = close_curve(ci)
                if cco is None or cci is None:
                    raise ValueError("outline did not close")
                out_sets.append(cco)
                in_sets.append(cci)
                wall_pairs.extend(zip(co, ci))

            cap_o = rg.Brep.CreatePlanarBreps(netlist(rg.Curve, out_sets), max(TOL, FIT))
            cap_i = rg.Brep.CreatePlanarBreps(netlist(rg.Curve, in_sets), max(TOL, FIT))
            if not cap_o or not cap_i:
                raise ValueError("cap failed")

            walls = []
            for (O, I) in wall_pairs:
                lo, li = O.GetLength(), I.GetLength()
                if lo < FIT and li < FIT:
                    continue
                if lo < FIT:
                    b = rg.Brep.CreateFromCornerPoints(O.PointAtStart, I.PointAtStart, I.PointAtEnd, TOL)
                elif li < FIT:
                    b = rg.Brep.CreateFromCornerPoints(I.PointAtStart, O.PointAtStart, O.PointAtEnd, TOL)
                else:
                    lf = rg.Brep.CreateFromLoft(netlist(rg.Curve, [O, I]),
                                                rg.Point3d.Unset, rg.Point3d.Unset,
                                                rg.LoftType.Straight, False)
                    b = lf[0] if lf and len(lf) > 0 else None
                if b is None:
                    raise ValueError("wall failed")
                walls.append(b)

            allb = list(cap_o) + list(cap_i) + walls
            jn = rg.Brep.JoinBreps(netlist(rg.Brep, allb), max(TOL, FIT))
            if jn and len(jn) >= 1:
                cand = jn[0]
                if not cand.IsSolid:
                    cp = cand.CapPlanarHoles(max(TOL, FIT))
                    if cp:
                        cand = cp
                if cand.IsSolid:
                    if cand.SolidOrientation == rg.BrepSolidOrientation.Inward:
                        cand.Flip()
                    solid = cand
                else:
                    raise ValueError("join gave %d breps from %d, not solid (naked edges %d)"
                                     % (len(jn), len(allb),
                                        len([e for e in cand.Edges if e.Valence == rg.EdgeAdjacency.Naked])))
            else:
                raise ValueError("JoinBreps returned nothing from %d faces" % len(allb))
            outer_flat = out_sets
        except Exception as ex:
            solid = None
            warn.append("%s (Sp[%d].F%d) miter build failed: %s" % (me, bi, fi, ex))

    if solid is None:
        slab = rg.Brep.CreateFromOffsetFace(f, (H_IN - H_OUT), TOL, False, True)
        if slab is None:
            slab = rg.Brep.CreateFromOffsetFace(f, -T, TOL, False, True)
        if slab is not None:
            if slab.IsSolid and slab.SolidOrientation == rg.BrepSolidOrientation.Inward:
                slab.Flip()          # an inside-out slab poisons every downstream boolean
            solid = slab
            fallbacks.append(me)
        else:
            skipped.append("%s  (Sp[%d].F%d)  could not be built at all" % (me, bi, fi))
            continue

    P.append(solid)
    ctr = rg.AreaMassProperties.Compute(f.DuplicateFace(False))
    A.append(rg.TextDot(me, ctr.Centroid if ctr else solid.GetBoundingBox(True).Center))

    if outer_flat is None:
        oc = None
        for lp in f.Loops:
            if lp.LoopType == rg.BrepLoopType.Outer:
                oc = flatten(lp.To3dCurve(), plane)
        outer_flat = [oc] if oc else []
    if kept_recs is not None and me not in fallbacks:
        edge_recs = kept_recs          # exactly the edges the built panel has
    else:
        edge_recs = []
        for (ltype, recs) in loops:
            for r in recs:
                edge_recs.append(r)
    parts.append({"id": me, "bi": bi, "plane": plane, "curves": outer_flat,
                  "recs": edge_recs, "area": area, "fallback": me in fallbacks})


# ------------------------------------------------------------- base plate

B = []
plate_parts = []
src = []
if have_plate:
    for brep in Sb_l:
        if not isinstance(brep, rg.Brep):
            continue
        for fi in range(brep.Faces.Count):
            pl, _ = face_plane(brep.Faces[fi])
            if pl is not None and abs(pl.Normal * rg.Vector3d.ZAxis) >= ground_dot:
                src.append((brep, fi, pl))
else:
    for bi, brep in enumerate(Sp_l):
        if not isinstance(brep, rg.Brep):
            continue
        for fi in range(brep.Faces.Count):
            pl, _ = face_plane(brep.Faces[fi])
            if pl is not None and abs(pl.Normal * rg.Vector3d.ZAxis) >= ground_dot:
                src.append((brep, fi, pl))

for (brep, fi, pl) in src:
    f = brep.Faces[fi]
    s = 1.0 if (pl.Normal * rg.Vector3d.ZAxis) > 0 else -1.0
    sol = rg.Brep.CreateFromOffsetFace(f, -T * s, TOL, False, True)
    if sol:
        B.append(sol)
    lbl = "BP%d" % len(B)
    fc = rg.AreaMassProperties.Compute(f.DuplicateFace(False))
    org = fc.Centroid if fc else f.DuplicateFace(False).GetBoundingBox(True).Center
    fplane = rg.Plane(org, rg.Vector3d.ZAxis)
    crvs, recs = [], []
    for lp in f.Loops:
        if lp.LoopType not in (rg.BrepLoopType.Outer, rg.BrepLoopType.Inner):
            continue
        c = lp.To3dCurve()
        if c is None:
            continue
        c = flatten(c, fplane)
        crvs.append(c)
        segs = c.DuplicateSegments()
        if segs is None or len(segs) == 0:
            segs = [c]
        for sg in segs:
            recs.append({"seg": sg, "bevel": 90.0, "fold": 180.0, "shift": 0.0,
                         "kind": "square", "mate": "", "joint": 0})
    if crvs:
        plate_parts.append({"id": lbl, "bi": 9999, "plane": fplane, "curves": crvs,
                            "recs": recs, "area": (fc.Area if fc else 0.0), "fallback": False})


# ------------------------------------------- flat layout: shelf pack per building

FL, BV = [], []
TARGET = rg.Plane(rg.Point3d(0, 0, 0), rg.Vector3d.XAxis, rg.Vector3d.YAxis)
GAP = max(3.0, T * 1.5)

layout = parts + plate_parts
groups = {}
for p in layout:
    groups.setdefault(p["bi"], []).append(p)

# flatten every part once, measure it
for p in layout:
    x = rg.Transform.PlaneToPlane(p["plane"], TARGET)
    fc = []
    for c in p["curves"]:
        cc = c.DuplicateCurve()
        cc.Transform(x)
        fc.append(cc)
    if not fc:
        p["skip"] = True
        continue
    bb = fc[0].GetBoundingBox(True)
    for c in fc[1:]:
        bb.Union(c.GetBoundingBox(True))
    p["fcurves"] = fc
    p["xform"] = x
    p["w"] = bb.Max.X - bb.Min.X
    p["h"] = bb.Max.Y - bb.Min.Y
    p["min"] = bb.Min
    p["skip"] = False

# one global sheet width, so every building block lines up and the whole layout
# comes out roughly square instead of a long strip
_all = [p for p in layout if not p.get("skip")]
if _all:
    _tot = sum(q["w"] * q["h"] for q in _all)
    SHEET_W = max(math.sqrt(_tot) * 1.25, max(q["w"] for q in _all) * 1.02)
else:
    SHEET_W = 100.0

y_cursor = 0.0
for bi in sorted(groups.keys()):
    items = [p for p in groups[bi] if not p.get("skip")]
    if not items:
        continue
    items.sort(key=lambda q: -q["h"])
    width = SHEET_W
    x_cursor, row_h, block_top = 0.0, 0.0, y_cursor
    for p in items:
        if x_cursor > 0 and x_cursor + p["w"] > width:
            x_cursor = 0.0
            y_cursor += row_h + GAP
            row_h = 0.0
        shift = rg.Transform.Translation(x_cursor - p["min"].X, y_cursor - p["min"].Y, 0)
        total_x = rg.Transform.Multiply(shift, p["xform"])
        for c in p["fcurves"]:
            cc = c.DuplicateCurve()
            cc.Transform(shift)
            FL.append(cc)
        bb2 = FL[-1].GetBoundingBox(True)
        for r in p["recs"]:
            ec = r["seg"].DuplicateCurve()
            ec.Transform(total_x)
            if r["kind"] != "square":
                BV.append(rg.TextDot("%.0f" % r["bevel"], ec.PointAtNormalizedLength(0.5)))
        lblpt = rg.Point3d(x_cursor + p["w"] * 0.5, y_cursor + p["h"] * 0.5, 0)
        BV.append(rg.TextDot(p["id"] + ("*" if p["fallback"] else ""), lblpt))
        x_cursor += p["w"] + GAP
        row_h = max(row_h, p["h"])
    y_cursor += row_h + GAP * 3.0
    BV.append(rg.TextDot("--- building %s ---" % (("%d" % (bi + 1)) if bi != 9999 else "BASE PLATE"),
                         rg.Point3d(-GAP * 6.0, (block_top + y_cursor) * 0.5, 0)))


# -------------------------------------------------------------- text report

TB = []
TB.append("MITER PANELS v2   T=%.2f   M=%d (%s)" % (T, M, {0: "inward", 1: "outward", 2: "centered"}[M]))
TB.append("panels=%d   base plates=%d   joints=%d" % (len(P), len(B), len(joint_no)))
TB.append("solids=%d of %d   flat parts=%d" % (len([b for b in P if b.IsSolid]), len(P), len(FL)))
if fallbacks:
    TB.append("UNMITERED FALLBACKS (marked * in the layout): %s" % ", ".join(fallbacks))
if skipped:
    TB.append("SKIPPED: %d - see warnings below" % len(skipped))
if dropped:
    TB.append("ABSORBED EDGES: %d - see warnings below" % len(dropped))
TB.append("")
TB.append("=== BEVEL TABLE ===")
TB.append("part, edge, length_mm, bevel_deg, fold_deg, setback_mm, type, mates")
for p in layout:
    for i, r in enumerate(p["recs"]):
        TB.append("%s, e%d, %.2f, %.1f, %.1f, %.2f, %s, %s"
                  % (p["id"], i, r["seg"].GetLength(), r["bevel"], r["fold"],
                     r["shift"], r["kind"], r.get("mate", "")))
TB.append("")
TB.append("=== JOINT SCHEDULE (each shared edge once) ===")
for row in sorted(joint_rows):
    TB.append(row)

# ------------------------------------------------- clash report (buildability)
# Two panels sharing a joint may leave a sub-mm artifact where 3+ miters meet -
# harmless. Two panels that do NOT share a joint but occupy the same space mean
# the model has a feature thinner than 2*T: at this thickness it cannot be built.
jsets = [set(r["joint"] for r in p["recs"] if r.get("joint", 0) > 0) for p in parts]
pbbs = [b.GetBoundingBox(True) for b in P]
clashes = []
for i in range(min(len(P), len(parts))):
    for j in range(i + 1, min(len(P), len(parts))):
        ba = rg.BoundingBox(pbbs[i].Min, pbbs[i].Max)
        ba.Inflate(-0.05)
        bb = rg.BoundingBox(pbbs[j].Min, pbbs[j].Max)
        bb.Inflate(-0.05)
        it = rg.BoundingBox.Intersection(ba, bb)
        if not it.IsValid or it.Volume <= 0.05:
            continue
        NS, hits = 5, 0
        for xi in range(NS):
            for yi in range(NS):
                for zi in range(NS):
                    pt = rg.Point3d(it.Min.X + (it.Max.X - it.Min.X) * (xi + 0.5) / NS,
                                    it.Min.Y + (it.Max.Y - it.Min.Y) * (yi + 0.5) / NS,
                                    it.Min.Z + (it.Max.Z - it.Min.Z) * (zi + 0.5) / NS)
                    if P[i].IsPointInside(pt, TOL, True) and P[j].IsPointInside(pt, TOL, True):
                        hits += 1
        if hits == 0:
            continue
        ov = it.Volume * hits / float(NS ** 3)
        if ov < 0.5:
            continue
        clashes.append((ov, parts[i]["id"], parts[j]["id"], len(jsets[i] & jsets[j]) > 0))
clashes.sort(reverse=True)
real = [c for c in clashes if not c[3]]
TB.append("")
TB.append("=== CLASH REPORT ===")
TB.append("%d clashing pairs, %d of them real (panels that do not share a joint)" % (len(clashes), len(real)))
if real:
    TB.append("A real clash means the model has a feature thinner than 2*T=%.1f mm there." % (2 * T))
for (ov, a, b, shared) in clashes[:40]:
    TB.append("%-8s x %-8s %8.2f mm3   %s"
              % (a, b, ov, "corner artifact (shared miter, harmless)" if shared else "REAL CLASH"))
if warn or skipped or dropped:
    TB.append("")
    TB.append("=== WARNINGS ===")
    for w in skipped:
        TB.append("SKIPPED  " + w)
    for w in dropped:
        TB.append("ABSORBED " + w)
    for w in warn:
        TB.append("WARN     " + w)
