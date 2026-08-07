# Starting prompt

Paste everything between the lines into the agent as your first message.

---

I'm building a web-based assembly guide for a 1:200 physical architecture model.
Everything you need is in this repo. **Read these first, in order:**

1. `README.md` — what the project is, the numbers, and the angle convention
2. `docs/AssemblyGuide_HANDOFF.md` — the full build spec. This is the plan; follow it.
3. `docs/MiterPanels_HANDOFF.md` — how the parts were generated, plus the Rhino-bridge
   gotchas that have burned previous sessions

## Do Phase 1 only for now

Per §1b and §9 of the spec, this is a two-phase job. **Phase 1** is writing
`rhino/export_assembly_json.py` and producing `assembly_data.js`. Do not start the web
tool until the exported data verifies. Ask me before you begin Phase 2.

## How to reach the geometry: CodeListener + my live Rhino window

The geometry is **not in this repo**. It's in a Rhino session I have open right now:

- Rhino is open with `C:\Users\nrahn\Downloads\260728_1zu200 Umgebungsgebäude.3dm`
- Grasshopper is open with the `miters` definition, solved
- **CodeListener is running on port 614**

Use the `execute_grasshopper_code` MCP tool to run Python **live inside that Rhino
session**. The data you need is on the open document's `Final::` layers and on the live
Grasshopper Python component's outputs (`P`, `B`, `A`, `FL`, `BV`, `TB`).

If that MCP tool isn't available to you, stop and tell me — the same MCP server I use
in the desktop app needs configuring for this workspace. (Fallback: the export script
is ordinary RhinoPython, so I can run it myself with `_RunPythonScript` and no
listener at all. It just means you can't iterate on it directly.)

### Bridge rules — these are not optional, each one has cost a previous session hours

- The listener is **IronPython 2.7**: `%` formatting, no f-strings, and
  `# -*- coding: utf-8 -*-` at the top of any file with non-ASCII (the model name has
  an umlaut).
- **The bridge response is truncated.** `print` is unreliable for anything longer than
  a line or two, and some characters kill the response entirely. Write results with
  `System.IO.File.WriteAllText(...)` and read the file back with your Read tool.
- For any script longer than a few lines: write it to a file, `System.IO.File.Copy` it
  to `C:\Users\nrahn\Documents\RhinoScripts\`, then `execfile` it from the bridge.
  My scratchpad/temp directory is on the real filesystem and Rhino can read it — don't
  bother with base64 blobs, hand-transcribing one corrupts it.
- **Reuse `rhino/_np_helpers.py`** for board-curve matching. Do not re-implement it.
  In particular use its arc-length `centroid()` — `AreaMassProperties.Compute` returns
  None on some outlines and the bounding-box fallback silently breaks every alignment.

### Read-only — the model is finished and the parts are already milled

Do not modify the Grasshopper definition, and do not modify or delete anything on the
`Final::` layers. Phase 1 only reads. If you need to write anything into the Rhino
document, ask me first.

## Verify before moving on

The export must produce **exactly** these counts. If any is off, stop and diagnose —
everything downstream inherits the error:

- 138 panels + 3 base plates
- 726 edge rows, of which **430** have `needsWork: true`
- 154 board outline curves (91 on Board 1, 63 on Board 2)
- 225 joints
- 14 buildings

Then spot-check 3 random parts against `docs/CutList_MiterAngles.txt` — the angles must
match exactly.

## Two things I care about most

- **The 3D view is the point of the tool, not decoration.** I did a training project
  with a Rhino window open in the shop and stepped through every part in 3D; seeing the
  miters and where the piece sits is what makes it click. Build that first and build it
  well.
- **It has to work on my iPhone**, hosted on GitHub Pages, and it has to save progress
  reliably.
