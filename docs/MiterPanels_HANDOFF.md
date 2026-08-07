# Miter Panels GH Tool - Handoff  (v2, 2026-08-03)

## What this is
A reusable Grasshopper tool that converts a planar open polysurface (building shell + base plate)
into fabrication-ready parts: 3D mitered panels, a flat cut layout, a bevel table, a joint
schedule and a clash report. Goal: reproduce a plywood/card model - hollow buildings with precise
miters sitting on a base plate. Designed to work on ANY project.

## Live Rhino/GH link (how an agent drives it)
- CodeListener must be running in Rhino (port 614). Tool `mcp__GH_mcp_server__execute_grasshopper_code`
  runs Python LIVE inside Rhino. The listener is IronPython 2.7 - use % formatting, no f-strings,
  add `# -*- coding: utf-8 -*-` for non-ASCII.
- **FILE TRANSPORT (important, corrects the old note):** the agent's scratchpad directory
  (`%LOCALAPPDATA%\Temp\claude\<project>\<session>\scratchpad`) IS on the real filesystem and Rhino
  can read it directly. So: write the script with the normal Write/Edit tools, then in the bridge do
  `System.IO.File.Copy(scratchpad_path, real_path, True)`. Verified by md5. Do NOT bother with
  base64/zlib blobs - hand-transcribing a long blob into a tool call corrupts it.
- **STDOUT IS UNRELIABLE.** Two separate effects:
  (a) when the GhPython component actually solves it steals stdout, and
  (b) the bridge response itself gets truncated - long prints and prints containing certain
      characters simply do not come back.
  Workaround for everything: `System.IO.File.WriteAllText(...)` then read the file with the Read tool.
- Rhino viewport screenshots DO work: `view.CaptureToBitmap(Size, False, False, False).Save(path)`.
  `vp.ZoomBoundingBox` is unreliable after manually setting the camera - isolate the objects on a
  layer, hide the rest, set `vp.SetCameraDirection`, then
  `Rhino.RhinoApp.RunScript("-_Zoom _All _Extents _Enter", False)`. Disable GH preview first
  (`ghdoc.PreviewMode = GH_PreviewMode.Disabled`) or TextDots bury the model.

## Files (real machine)
- `C:\Users\nrahn\Documents\RhinoScripts\MiterPanels.py`  <-- SOURCE OF TRUTH (the component's code).
  To update the live component: read this file, set `comp.Code`, then `ExpireSolution(True)` +
  `ghdoc.NewSolution(True)`.
- Same folder has one-off probe/diag scripts and `_*.txt` logs - ignore.

## The GH component
GhPython ZuiPythonComponent inside group "MITER PANELS tool".

Inputs:
- Sp (List access, **Brep TypeHint REQUIRED**) = miter pieces (walls/roof, open polysurface)
- Sb (List access, Brep TypeHint) = base plate(s), OPTIONAL. If empty, near-horizontal faces in Sp
     are auto-detected as the ground plate.
- T  = thickness (number slider)     - M = 0 inward / 1 outward / 2 centered (integer slider)

Outputs:
- P  = 3D mitered panels (closed solids)
- B  = base plate solid(s), thickened DOWN, cutouts preserved
- A  = part-ID TextDots, **index-aligned with P** (A[i] labels P[i])
- FL = flat cut outlines, shelf-packed one block per building on world XY
- BV = bevel TextDots + part labels on the flat layout
- TB = text report: bevel table + joint schedule + CLASH REPORT + warnings

CRITICAL: Sp/Sb MUST have a Brep TypeHint, else a referenced Rhino object arrives as a
System.Guid and the script silently outputs nothing (NO error):
  `comp.Params.Input[i].TypeHint = Grasshopper.Kernel.Parameters.Hints.GH_BrepHint()`

## v2 algorithm (replaced v1 entirely)

**What v1 did wrong** - keep this, it is easy to reinvent:
1. It mitered by trimming each slab with an **infinite** bisector plane (`Brep.Trim(plane, tol)`).
   On any face that is not convex, that plane also slices through distant parts of the SAME panel.
   Measured on the real project: panels kept 6%-50% of their volume, losses scaling with edge count
   (a 12-edge roof kept 25%; the largest face kept 19%). On some breps `Trim` returned nothing and
   the code silently fell back to an unmitered slab.
2. It used `f.TryGetPlane(doc_tolerance)` only, so every face that was planar-but-not-within-0.001
   was skipped with no error. On the real project that silently dropped 16 of 98 faces.

**What v2 does** - build the panel directly, no booleans, no infinite trims:
- outer outline = the face outline at height `h_out` along the outward normal n
- inner outline = each edge offset **in-plane by its own setback**
      `a(h) = -h * (n . m) / (inA . m)`
  where `m` = unit normal of the bisector plane at that edge, `inA` = in-plane direction into the
  face. This is sign-correct automatically for convex AND reentrant corners (a reentrant corner
  gives a negative setback, i.e. the inner face extends past the edge - which is right).
  `h_out/h_in` = (0,-T) for M=0, (T,0) for M=1, (T/2,-T/2) for M=2.
- bevel = `atan2(T, a_in - a_out)` in degrees (90 = square, 45 = normal box corner, 135 = reentrant);
  fold angle = 2*bevel.
- offsets are exact for lines and arcs, generic `Curve.Offset` otherwise.
- corners: extend both offset curves, intersect, take the hit nearest the original corner and
  within a distance limit; if there is no hit the corner opens and a bridge line is inserted.
  A corner is treated as closed only if BOTH heights resolved it, so the outer and inner outlines
  keep identical structure and the side walls pair up 1:1.
- side walls = ruled loft per edge; degenerate (zero-length outer bridge) becomes a triangle.
- join + `IsSolid` check + orientation flip (Inward -> Flip, otherwise every downstream boolean
  returns nonsense).

**Robustness rules that matter:**
- Plane detection walks a tolerance ladder (doc tol, .01, .05, .1, .5, 2.0) then a least-squares
  fit; near-planar faces are flattened onto that plane and REPORTED, never dropped.
- Faces with area < MIN_AREA (0.5 mm^2) are skipped and reported as degenerate slivers.
- Arc extension is capped so total sweep stays under 340 deg. Beyond that the extension wraps onto
  itself, curve parameters stop being monotonic and every later `Trim` silently inverts. This was
  the cause of 4 of the 6 remaining failures.
- A segment too short to survive its neighbours' setbacks is DROPPED and the loop re-solved
  (reported as "ABSORBED"), instead of failing the whole panel.
- If a panel still cannot be built it falls back to an unmitered slab and is flagged `*` in the
  layout - a piece is never silently missing.

## Verified state on the real project (260728_1zu200 Umgebungsgebaeude.3dm)
7 building shells (98 faces) + a 3-face stepped site plate, T=4, M=0, mm, tol 0.001.
- P = 96 panels, **96/96 closed solids** (v1: 82 panels, badly eroded)
- 2 skipped = genuinely degenerate source faces (area 0.000 and 0.012 mm^2)
- 1 unmitered fallback = 7.11, a 6.5 mm^2 face that cannot be mitered at T=4
- 11 absorbed edges, 9 of them sub-millimetre modelling noise (0.02-0.16 mm)
- 161 joints, solve time ~3.2 s (the clash check is ~2.7 s of that)
- Panel volume vs area*T now 0.85-1.05 (correct miter signature); total panel-to-panel overlap
  0.23% of volume, and every ADJACENT pair overlaps by <= 13 mm^3 (corner artifacts where 3+ miters
  meet - the exact 3D solution at such a vertex is a small pyramid the per-edge construction
  approximates; irrelevant at 1:200 where kerf alone is ~0.2 mm).

## Open issues for THIS project (not tool bugs)
- 19 REAL clashes in the clash report: pairs of panels that do NOT share a joint but occupy the
  same space => the model has features thinner than 2*T = 8 mm there. Biggest: 5.5 x 6.9 (967 mm^3)
  and 5.6 x 6.1 - those two are between DIFFERENT buildings (Sp[4] and Sp[5]), i.e. the source
  buildings interpenetrate. Fix in the source model, or use a thinner T for those buildings.
  7.12 x 7.16 (518 mm^3) and 7.19 x 7.21 are within building 7, which is only ~33 mm wide.
- Flat layout is 887 x 1730 mm, one block per building, shelf-packed to a single global width.
  Real nesting is still deliberately deferred to the Laserscript / OpenNest tool.

## Good next steps (not built)
- Feed FL into the Laserscript fabrication tool for real nesting + layer/piece numbering.
- Engrave the part ID into each flat outline instead of only a TextDot.
- Per-building T (thin buildings need T=2 to clear the clash report).

## Related agent memory files
- miter-panels-gh-tool.md (this tool)
- rhino-gh-mcp-setup.md (CodeListener/bridge)
- shell-sandbox-fs-isolation.md (see the corrected file-transport note above)
- laserscript-fabrication-tool.md (nesting/laser pipeline this can feed)


---

# Part 2 - CNC board numbering + machine angles (2026-08-07)

## Angle convention (CONFIRMED with Niklas - do not re-derive)
The number the tool puts on the flat layout is **half the fold angle**: 90 = square
edge, 45 = ordinary square building corner, 135 = reentrant corner.

    saw tilt = 90 - shown          (0 on Niklas's scale = blade square to the face)

- tilt negative (shown > 90) -> **FLIP** the piece over and set |tilt|
- |tilt| > 45 (shown < 45)   -> **45 deg JIG**, set |tilt| - 45  (his saw only reads 0-45)

The anchor that settles it: 176 of 446 edges on this project show 45, which is the
ordinary square building corner, and that is cut with the blade at 45. Any mapping
that sends 45 to something else is wrong. (Niklas initially recalled "65 -> 20";
the correct value is 65 -> 25. 65 - 45 = 20 is the jig rule applied to the wrong
number.)

Labels written on the ...Angles layers: `25`, `F25` (flip), `J7` (jig),
`FJ2` (both), `sq` (square).

**Mirroring matters.** In the flat layout +Z is the panel's OUTER face. If a nest
instance is mirrored (transform determinant < 0) the piece lies outer-face-DOWN on
the board, so the FLIP flag inverts. `apply_numbering.py` XORs this in; 21 of the
138 placed parts on this project are mirrored.

## Scripts
- `apply_numbering.py` - writes part-number and machine-angle TextDots onto
  `Final::FinalCNCBoard1/2`. ADDITIVE: it only creates
  `Final::FinalCNCBoard{1,2}{Numbers,Angles}` and never touches existing objects
  or the GH definition. Re-runnable (it clears its own layers first).
- `_np_helpers.py` - shared gather/match/fit helpers. `apply_numbering.py` and the
  diagnostics both `execfile` this; do NOT copy-paste these functions, an earlier
  divergent copy caused the centroid bug below.
- Output report: `CutList_MiterAngles.txt` (convention, matching stats, per-part cut list).

## How board curves are matched back to parts
Each closed curve on a board is a rigid (optionally mirrored) copy of one outline in
`Final::FinalOutputFlat`. Candidates from perimeter/area/radial-profile, then
**verified by actually fitting the transform** and measuring max deviation over 40
samples. <=0.25 mm = CONFIRMED, <=1.5 mm = PROBABLE (labelled with a trailing `?`),
otherwise the curve gets an `X`.

**THE BUG THAT COST THE MOST TIME:** `AreaMassProperties.Compute` returns None on
some of the flat outlines, and the fallback was the *bounding-box* centre while the
board curve used the *area* centroid - two different reference points, so every
alignment for those parts came out 2-22 mm off and 13 parts looked "missing".
Fix: `centroid()` is now the **arc-length centroid** (mean of 200 equally spaced
points), which is defined for any closed curve and invariant under rotation,
translation and mirroring. Never use AreaMassProperties for this.

Also note the board polylines are re-segmented relative to the flat outlines (an
87.5 mm edge can appear as 42.04 + 21.87 + ...), so do NOT verify a match by
comparing segment lengths - compare fitted deviation instead.

## State of the boards on this project
- 150 closed curves: 131 CONFIRMED, 7 PROBABLE, 11 unidentified, 1 board outline.
- 138 of 141 final parts are on a board. **7.8, 7.9 and 7.10 are NOT nested on
  either board and still have to be cut.**
- The 3 base plates were hand-edited after nesting (a notch was closed: area +2.3
  to +5.6%, perimeter within 0.2% except BP3 at -8.3%), so they never fit rigidly.
  They are matched on size alone and labelled `BP1?` `BP2?` `BP3?`. They carry no
  bevels - every plate edge is square - so no transform is needed for them.
- The 11 `X` curves are leftovers from an earlier version. Seven of them cluster at
  around (390..560, -900..-975) on Board1 and their areas are exactly the seven face
  areas of the old 7-face tower from the first version of the model. Cut into the
  board, but not part of the final model - do not use them.
- 397 bevelled edges: 32 need the jig, 100 need the piece flipped.

## Gotcha carried over
The Rhino bridge truncates its response, so `print` is unreliable for anything
longer than a line or two. Everything here writes to a file and the agent reads it
back. Long scripts: write to the scratchpad, `System.IO.File.Copy` to
`Documents\RhinoScripts`, then `execfile` it - see [[shell-sandbox-fs-isolation]].
