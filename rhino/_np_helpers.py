# -*- coding: utf-8 -*-
"""Shared helpers for the board-numbering work."""
import Rhino
import Rhino.Geometry as rg
import math, re

doc = Rhino.RhinoDoc.ActiveDoc
BOARDS = ["Final::FinalCNCBoard1", "Final::FinalCNCBoard2"]
relbl = re.compile(r'^(\d+\.\d+\*?|BP\d+)$')
renum = re.compile(r'^-?\d+$')


def lay_objs(name):
    i = doc.Layers.FindByFullPath(name, -1)
    return list(doc.Objects.FindByLayer(doc.Layers[i])) if i >= 0 else []


def centroid(c, N=200):
    """Arc-length centroid: the mean of N points spaced equally along the curve.

    Deliberately NOT AreaMassProperties - that fails on some of the flat outlines
    (returns None) and the bounding-box fallback is a different reference point,
    so a failing part and a working board curve got anchored on two different
    origins and every alignment came out garbage. This is defined for any closed
    curve and is invariant under rotation, translation and mirroring."""
    ln = c.GetLength()
    sx = sy = 0.0
    for i in range(N):
        p = c.PointAtLength(ln * i / float(N))
        sx += p.X
        sy += p.Y
    return rg.Point3d(sx / N, sy / N, 0.0)


def area_of(c):
    a = rg.AreaMassProperties.Compute(c)
    return a.Area if a else -1.0


def verts(c):
    ok, pl = c.TryGetPolyline()
    if ok and pl.Count > 1:
        return [pl[i] for i in range(pl.Count - 1)]
    segs = c.DuplicateSegments()
    if segs and len(segs) > 0:
        return [s.PointAtStart for s in segs]
    return []


def profile(c, N=120):
    ctr = centroid(c)
    ln = c.GetLength()
    ds = []
    for i in range(N):
        p = c.PointAtLength(ln * i / float(N))
        ds.append(math.hypot(p.X - ctr.X, p.Y - ctr.Y))
    ds.sort()
    return ds


def prof_dist(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / float(len(a))


def frame(o, p):
    x = rg.Vector3d(p.X - o.X, p.Y - o.Y, 0.0)
    if x.Length < 1e-9:
        return None
    x.Unitize()
    return rg.Plane(o, x, rg.Vector3d.CrossProduct(rg.Vector3d.ZAxis, x))


def fit_transform(src, dst):
    cd = centroid(dst)
    vd = verts(dst)
    if not vd:
        return None, 1e9
    ln = src.GetLength()
    samples = [src.PointAtLength(ln * i / 40.0) for i in range(40)]
    best_xf, best_dev = None, 1e9
    for mirror in (False, True):
        s2 = src.DuplicateCurve()
        mir = rg.Transform.Identity
        if mirror:
            mir = rg.Transform.Mirror(rg.Plane(centroid(src), rg.Vector3d.XAxis))
            s2.Transform(mir)
        c2 = centroid(s2)
        v2 = verts(s2)
        if not v2:
            continue
        w0 = max(v2, key=lambda p: p.DistanceTo(c2))
        r0 = w0.DistanceTo(c2)
        fsrc = frame(c2, w0)
        if fsrc is None:
            continue
        cands = [w for w in vd if abs(w.DistanceTo(cd) - r0) < 0.35]
        if not cands:
            cands = sorted(vd, key=lambda w: abs(w.DistanceTo(cd) - r0))[:3]
        for w in cands[:8]:
            fdst = frame(cd, w)
            if fdst is None:
                continue
            xf = rg.Transform.Multiply(rg.Transform.PlaneToPlane(fsrc, fdst), mir)
            dev = 0.0
            for p in samples:
                q = rg.Point3d(p)
                q.Transform(xf)
                rc, t = dst.ClosestPoint(q)
                if not rc:
                    dev = 1e9
                    break
                d = dst.PointAt(t).DistanceTo(q)
                if d > dev:
                    dev = d
                if dev >= best_dev:
                    break
            if dev < best_dev:
                best_dev, best_xf = dev, xf
    return best_xf, best_dev


def gather_flats():
    label_dots = [o.Geometry for o in lay_objs("Final::FinalTextDots")
                  if relbl.match(o.Geometry.Text.strip()) and abs(o.Geometry.Point.Z) < 1e-6]
    angle_dots = [o.Geometry for o in lay_objs("Final::FinalTextDots")
                  if renum.match(o.Geometry.Text.strip()) and abs(o.Geometry.Point.Z) < 1e-6]
    flats = []
    for o in lay_objs("Final::FinalOutputFlat"):
        b = o.Geometry
        if not isinstance(b, rg.Brep) or b.Faces.Count < 1:
            continue
        crv = None
        for lp in b.Faces[0].Loops:
            if lp.LoopType == rg.BrepLoopType.Outer:
                crv = lp.To3dCurve()
        if crv is None:
            continue
        bb = crv.GetBoundingBox(True)
        cx = (bb.Min.X + bb.Max.X) * 0.5
        cy = (bb.Min.Y + bb.Max.Y) * 0.5
        best, bd = None, 1e18
        for d in label_dots:
            dd = math.hypot(d.Point.X - cx, d.Point.Y - cy)
            if dd < bd:
                bd, best = dd, d
        flats.append({"crv": crv, "id": (best.Text.strip() if best and bd < 0.6 else "?"),
                      "a": area_of(crv), "p": crv.GetLength(), "prof": profile(crv),
                      "bev": [], "used": False})
    orphan = 0
    for d in angle_dots:
        best, bd = None, 1e18
        for f in flats:
            rc, t = f["crv"].ClosestPoint(d.Point)
            if not rc:
                continue
            dist = f["crv"].PointAt(t).DistanceTo(d.Point)
            if dist < bd:
                bd, best = dist, f
        if best is not None and bd < 0.5:
            best["bev"].append((d.Point, float(d.Text.strip())))
        else:
            orphan += 1
    return flats, angle_dots, orphan


def gather_boards():
    boards = []
    for bn in BOARDS:
        for o in lay_objs(bn):
            c = o.Geometry
            if isinstance(c, rg.Curve) and c.IsClosed:
                boards.append({"bn": bn, "crv": c, "a": area_of(c), "p": c.GetLength(),
                               "m": None, "dev": None, "xf": None, "status": "UNKNOWN"})
    return boards


def mark_board_outline(boards):
    for bn in BOARDS:
        grp = [b for b in boards if b["bn"] == bn]
        if not grp:
            continue
        big = max(grp, key=lambda b: b["a"])
        rest = sorted([b["a"] for b in grp if b is not big], reverse=True)
        if rest and big["a"] > 3.0 * rest[0]:
            big["status"] = "BOARD OUTLINE"
