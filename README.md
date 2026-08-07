# Assembly Guide — 1:200 Umgebungsgebäude

A web tool that guides the physical assembly of a 1:200 architectural context model:
which piece goes where, seen in 3D, and exactly how to sand each miter.

**Status:** phase 1 and phase 2 both built. `assembly_data.js` is exported and verified,
and `index.html` is the tool. What is left is yours, not the code's: put it on a host
with https and test it on the actual phone (see **Deployment** below).
`docs/AssemblyGuide_HANDOFF.md` is the build spec. Rhino is no longer needed.

Open `index.html` directly in a browser on the laptop and it works — the 3D view, the
angles, the board maps, all of it. Only offline caching and the screen-stays-on lock
need a real https origin.

---

## The physical project

14 context buildings ("Umgebungsgebäude") at 1:200, built as **hollow shells** from
**4 mm** sheet material sitting on a 3-piece stepped base plate. Every corner is a
**mitered** joint, so the panels meet cleanly with no end-grain showing.

The parts were generated parametrically in Grasshopper, nested onto two CNC boards,
and **the boards are already milled**. So every edge is currently **square**. The
remaining physical work is:

1. **sand 430 bevels** on a small disc sander with a tilting table
2. **glue up 141 parts** into 14 buildings on the base plate

That is what this tool guides.

## The numbers (measured, not estimated)

| | |
|---|---|
| panels | **138** (+3 base plates) |
| buildings | 14 — parts each: 7, 13, 6, 6, 12, **33**, **26**, 7, 4, 5, 5, 5, 4, 5 |
| total edges | 726 |
| edges already correct as milled (square/flat) | 296 |
| **edges still needing a bevel** | **430** |
| joints (part ↔ part pairs) | 225 |
| distinct machine settings | 44 — but 224 of 430 edges are at 45° |
| edges needing the piece flipped | 70 |
| edges needing the 45° jig | 36 |
| total mesh triangles, all panels | 10 200 |
| model bounding box | 482 × 626 × 176 mm |
| material thickness `T` | 4.0 mm |

## The angle convention — read this before touching any angle

The number printed on the flat layout is **half the fold angle**:
`90` = square edge, `45` = ordinary square building corner, `135` = reentrant corner.

```
sander table angle = 90 − shown        (0 on the scale = square to the board face)
```

- table angle negative (shown > 90) → **flip the piece over**, set the absolute value
- |angle| > 45 (shown < 45) → **45° jig**, set |angle| − 45 (the machine only reads 0–45)

**The anchor that settles it:** 178 of the 430 bevelled edges are at 45, which is the
ordinary square building corner, and that is 45° on the machine. Any mapping that
sends 45 somewhere else is wrong. Do not re-derive this — it was confirmed directly
with Niklas.

**Mirroring inverts the flip flag.** In the flat layout, +Z is the panel's OUTER face.
A part the nest mirrored lies outer-face-down on the board, so its flip instruction
reverses. `rhino/apply_numbering.py` already handles this — copy that logic.

## Part numbering

`building.part` — e.g. `7.17` is building 7, part 17. Base plates are `BP1`–`BP3`.

Two suffixes exist in the Rhino file and **must be normalised away** on export, or the
tool will treat them as different parts:

- `7.11*` — the `*` marks an unmitered fallback (a 6.5 mm² face too small to miter at
  T=4). The part is real and is on a board.
- `BP1?` `BP2?` `BP3?` — the `?` marks a size-only match, because the plates were
  hand-edited after nesting.

## Known issues to surface in the tool

- **The angle labels drawn on the CNC boards are incomplete — do not trust them.**
  Found during the phase-1 export. `Final::FinalTextDots` holds only **405** bevel dots
  where the live definition produces **446**, so that layer is stale, and
  `apply_numbering.py` propagated the gap into `Final::FinalCNCBoard{1,2}Angles` and into
  `docs/CutList_MiterAngles.txt`. **12 parts** carry fewer callouts on the board than they
  need: 2.1, 2.3, 2.4, 2.7, 5.5, 5.8, 5.11, 6.6, 6.32, 7.25, 9.3, 9.4 — and **2.1 and 2.4
  are marked as having no bevels at all when each needs six.** The exported data is taken
  from the live bevel table, not from the dots, so `assembly_data.js` is correct and is a
  strict superset of the cut list (verified: every label the cut list has, the export also
  has). The model geometry is *not* stale — every one of the 141 flat outlines still
  matches the milled board curves to within 0.002 mm.
- **Parts 7.8, 7.9 and 7.10 were never nested** on either board. 135 of 138 parts have
  a board location; these three still have to be made.
- **11 curves milled into the boards are leftovers** from an earlier version of the
  model. Seven cluster around (390…560, −900…−975) on Board 1 and their areas are
  exactly the seven face areas of an older version of one building. They are cut into
  the physical board — show them greyed out or someone will pick one up and use it.
- The 3 base plates' board outlines don't exactly match the model outlines (hand-edited
  after nesting: area +2.3 to +5.6 %). They're square-edged, so nothing depends on it.

## Where the source data lives

Everything is in a **live Rhino session**, not in this repo:

- `C:\Users\nrahn\Downloads\260728_1zu200 Umgebungsgebäude.3dm`
- Grasshopper definition `miters`, with one Python component whose outputs are
  `P` (panels), `B` (plates), `A` (part-ID dots, index-aligned with `P`),
  `FL`, `BV`, `TB` (bevel table + joint schedule)
- Rhino layers `Final::FinalOutputFlat`, `Final::FinalCNCBoard1` / `2`,
  `Final::FinalCNCBoard{1,2}Numbers` / `Angles`

Phase 1 pulls all of it into a single `assembly_data.js`. After that this repo is
self-contained and Rhino is no longer needed — see §1b of the spec.

## Repo layout

```
README.md                        this file
PROMPT.md                        starting prompt — paste into the agent
index.html                       THE TOOL — one file, no build step
assembly_data.js                 THE DATASET — 535 KB, all the tool needs
three.min.js                     vendored three.js r147 (UMD, not a CDN — offline)
OrbitControls.js                 vendored, r147 examples/js — touch orbit + pinch
sw.js                            service worker, precaches everything for the workshop
manifest.webmanifest             Add to Home Screen
icon-*.png                       app icons, generated
docs/
  AssemblyGuide_HANDOFF.md       THE BUILD SPEC — follow it
  MiterPanels_HANDOFF.md         how the parts were generated + bridge gotchas
  CutList_MiterAngles.txt        current per-part cut list — ground truth for verification
  Phase1_ExportReport.txt        the export's own verification report — read this
rhino/
  _np_helpers.py                 board-curve matching helpers — REUSE, don't rewrite
  apply_numbering.py             reference: mirror handling, additive-only discipline
  MiterPanels.py                 reference: the GH component that generates the parts
  export_assembly_json.py        PHASE 1 — read-only, produces assembly_data.js
```

Everything is vendored. There is no bundler, no `npm install`, and nothing is fetched
from a CDN at runtime — the shop wifi is not to be trusted.

## The tool

Four screens, reachable from the bar at the bottom.

- **3D model** — the whole site, parts coloured raw / bevelled / glued. Drag to orbit,
  pinch to zoom, **tap a part to open its card**. The strip along the top filters to one
  building and shows its progress.
- **Part card** — the piece highlighted in 3D inside the model with everything else
  ghosted, so you can see *where it goes and which way round*; then its flat true shape
  with every edge labelled, a tick per bevel, the mating part and its setting for each
  edge, and the board map with the piece in orange. Tap an edge row to light that edge up
  in both the 3D view and the flat drawing. `↑`/`↓` step along the assembly order.
- **Setups** — every remaining bevel grouped by **what the machine is set to**, biggest
  batch first. `45` and `F45` are deliberately one group: same table angle, the piece just
  goes on the other way up, so splitting them would hide that 222 of the 430 bevels share
  a single setting. 37 machine settings in total.
- **Progress** — how far along, export/import, and the export's warnings.

Alerts fire on the card automatically for the parts that need them: the 12 with wrong
board labels, the 3 that were never nested, the unmitered fallback, bevels with no mating
piece, sliver edges, and the 18 places where two parts clash at glue-up.

### Progress and how it is stored

`localStorage`, keyed by part id and a hash of the export, autosaved on every tick. Per
part it stores `bevelled`, `glued`, a note, **and which individual edges are done** — the
last of those is an addition to §6 of the spec, because the Setups screen batches by
machine setting and therefore leaves parts half-bevelled by design.

iOS can evict that storage on its own, so **Export progress** writes a small JSON file and
**Import** reads one back. That file is also how you move progress between the phone and
the laptop. Import warns if the file was made against a different export of the model, and
skips ids the model does not have.

### Verified against the cut list

Checked over all 138 parts, not a sample: every label in `docs/CutList_MiterAngles.txt`
is present in what the tool shows, with matching board and mirror state. The tool shows
*more* than the cut list on exactly the 12 parts documented below as having stale board
labels, and on no others. Spot-checking 7.17, 1.4 (mirrored) and 5.5, each label also
re-derives independently from `table = 90 − shown`, flipped where the nest mirrored it.

### Re-running the export

`rhino/export_assembly_json.py` is ordinary RhinoPython — `_RunPythonScript` it with the
.3dm open and the `miters` definition solved. It reads the component's own source and its
live inputs and re-executes them in a private namespace, because 27 edges are absorbed by
their neighbours' miters during solving and so the edge list cannot be recovered from the
outlines. It then diffs its regenerated bevel table and joint schedule against the
component's live `TB` output and aborts if they differ at all. Nothing is written to the
Rhino document.

> **Watch the helper path.** Rhino's `execfile` needs an absolute path, and the
> existing `apply_numbering.py` hardcodes
> `C:\Users\nrahn\Documents\RhinoScripts\_np_helpers.py` — that copy is the one that
> actually runs. The copy in `rhino/` here is for reading and version control. If you
> edit the helpers, edit the repo copy and copy it over to `RhinoScripts\` before
> running, or you will debug a file that isn't executing.

## Deployment

GitHub Pages, static, no build step. See §2.1 of the spec — Pages is chosen because a
service worker (offline in the workshop) and `navigator.wakeLock` (screen stays on at
the sander) both require a secure context, which a laptop-served `http://192.168.x.x`
does not provide.

Note: free GitHub Pages requires a **public** repo. If this needs to stay private,
Cloudflare Pages and Netlify both host from a private repo on their free tiers —
identical static files either way.

**This folder is not a git repo yet** — that call is yours, because publishing it makes
the model data public. Once you've decided:

```sh
git init && git add . && git commit -m "Assembly guide"
gh repo create AssemblyGuide --public --source=. --push     # or --private for CF/Netlify
```

Then Settings → Pages → deploy from `main` / root. Every path in the tool is relative, so
the project-subpath URL works as-is.

### Test on the phone before trusting it in the shop

In this order, on the iPhone, not the laptop:

1. open the Pages URL, **Add to Home Screen**, launch from the icon
2. orbit, pinch, and tap a part — confirm the card opens on the part you tapped
3. tick a few bevels, close the app completely, reopen — the ticks should still be there
4. **Export progress**, then Clear all, then Import the file back
5. turn wifi off and launch again — it should load with no connection at all
6. Progress → *keep screen on* and confirm it doesn't sleep at the sander
