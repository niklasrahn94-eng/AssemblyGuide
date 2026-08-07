# Assembly Guide Tool — Handoff / Build Spec

**Status:** specified, not built. Written 2026-08-07, revised after Niklas's feedback.
**Goal:** a web tool that walks Niklas through assembling the 1:200 Umgebungsgebäude
model part by part — **seeing each piece in 3D in the assembled model**, exactly how
to sand each of its miters, where to find it on the CNC board, with progress that
survives closing the browser. Must work on **iPhone** as well as a laptop.

> **The 3D view is the point of the tool, not a decoration.** Niklas did a training
> project this way with a Rhino window open in the shop and stepped through every
> part in 3D — seeing the miters and where the piece sits is what makes it click.
> Everything else in this spec is secondary to that.

---

## 1. Verdict: yes, comfortably

Everything the tool needs already exists in the Rhino file. Measured, not estimated:

| what | measured |
|---|---|
| panels | **138** (+3 base plates) |
| total triangles, all panels | **10 200** (avg 74/panel, worst 750) |
| all mesh geometry as naive JSON | ~389 KB uncompressed, ~200 KB at 2 dp |
| total edges across all parts | **726** |
| **edges already correct as milled** (square/90°) | **296** |
| **edges that still need a bevel** | **430** |
| distinct machine setups | 44 (but 224 of 430 edges are at one setting — 45°) |
| edges needing the piece flipped | 70 |
| edges needing the 45° jig | 36 |
| joint records (part ↔ part) | 225 |
| board outline curves for the board map | 91 + 63 (~1 265 polyline points) |
| buildings | 14 (4–33 parts each) |
| model bounding box | 482 × 626 × 176 mm |

10 200 triangles is a trivial load for any iPhone on WebGL. The whole dataset —
meshes, edges, board maps — fits in well under 1 MB.

**Everything is CNC milled, so every edge is square right now.** The tool's job is
therefore to guide **430 bevelling operations and 141 glue-ups** — not cutting. That
settles the state question: the two states are **`bevelled`** and **`glued`**.

**Assembly order is derivable.** I verified all 14 buildings have a fully connected
joint graph (no building splits into disconnected islands), which is exactly the
precondition for generating a sensible build sequence. See §4.

---

## 1b. Two phases — and only the first one touches Rhino

This is deliberately a two-step process, and the split is the useful part: phase 1
produces one small text file, and after that Rhino is out of the picture entirely.

| | phase 1 — export the data | phase 2 — build the tool |
|---|---|---|
| **needs Rhino open** | yes, with the .3dm and Grasshopper loaded | **no** |
| **needs the GH definition solved** | yes — the export reads `P`, `B`, `A`, `TB` straight off the component | no |
| **needs CodeListener (port 614)** | only if an *agent* is driving it | **no** |
| **produces** | `assembly_data.js` (~200–400 KB) | `index.html` + the rest of the repo |
| **how long** | seconds, run once | the actual work |
| **re-run when** | the model or the nesting changes | whenever |

**On CodeListener specifically:** it exists so an agent can execute Python inside your
running Rhino. `export_assembly_json.py` is an ordinary RhinoPython script — you can
equally run it yourself with `_RunPythonScript` and no listener at all. So you're never
blocked on having an agent session open just to regenerate the data.

Phase 2 needs nothing but the resulting `assembly_data.js`. That means it can be built
in any session, on any machine, with Rhino closed — and it's testable against the real
data from the first minute. Commit `assembly_data.js` to the repo; regenerating it is
a one-line change to the repo, not a rebuild.

---

## 2. Architecture

### 2.1 Delivery — GitHub Pages (decided)

**Do not** plan on a `file://` HTML for the phone. On iOS, opening a local HTML from
Files gives you a sandboxed preview where `localStorage` is unreliable or wiped between
launches — progress vanishes.

**GitHub Pages it is.** Beyond convenience, it is the only option that unlocks two
things, because both require a *secure context* (https, or localhost — a plain
`http://192.168.x.x` from the laptop does **not** qualify):

- **Service worker → real offline use.** Load it once on shop wifi, then it works with
  no connection at all. Without this, one bad-wifi moment kills you mid-build.
- **`navigator.wakeLock`** → the screen stops sleeping while you're at the sander.

Plus **Add to Home Screen** gives a fullscreen app with no browser chrome.

Repo layout — no build step, no bundler, just files:

```
/index.html            the tool
/assembly_data.js      window.ASSEMBLY = {...}   ← output of step 1
/three.min.js          vendored, NOT a CDN (offline)
/sw.js                 service worker, precache the four files above
/manifest.webmanifest  name, icons, display:standalone
```

Two caveats worth knowing before you push:

- **GitHub Pages from a *private* repo needs a paid plan.** On a free account the repo
  must be public, which means the model data is public too. It's context massing for a
  1:200 site model, so probably fine — but if this is coursework or client work you'd
  rather not publish, Cloudflare Pages and Netlify both host from a private repo on
  their free tiers. Same static files either way.
- Pages serves from the repo root or `/docs`; pick one and keep the paths relative
  (`./assembly_data.js`, not `/assembly_data.js`) or the project-subpath URL breaks it.

The same folder still opens fine as a plain `file://` page **on the laptop** for quick
checks — you just lose offline caching and wake lock, which don't matter there.

> Note: `fetch('data.json')` **fails on `file://`** in Chrome (opaque origin/CORS).
> Emitting the data as `assembly_data.js` with `window.ASSEMBLY = {...}` and a
> `<script src>` sidesteps it, and works identically over https. Don't switch to
> `fetch` just because Pages would allow it — you'd lose the laptop `file://` path.

### 2.2 3D renderer — use WebGL, and just use three.js

My earlier draft suggested a hand-rolled canvas2d painter's-algorithm renderer.
**That advice is wrong now that 3D is essential and iPhone is a target** — filling
10 000 paths per frame on canvas2d will crawl on a phone. Use WebGL.

**Recommendation: bundle three.js locally** (~600 KB min, ~150 KB gzipped when hosted).
It buys three things that matter here:

- `OrbitControls` with **touch support already correct** (one-finger orbit, pinch zoom)
- lighting/materials so the miter faces actually read as bevels — flat shading with a
  single light makes a 4 mm bevel nearly invisible
- **raycasting → tap a part in the 3D model to open its card.** This is the single
  best interaction in the tool and you get it free.

Bundle it in the folder, don't hit a CDN — the shop wifi may be bad and you want
offline. Raw WebGL is a viable lean alternative (~300 lines with shaders) but you'd be
reimplementing touch orbit and raycasting for no real gain.

### 2.3 iOS specifics to get right

- `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">`
- `touch-action: none` on the canvas, or the page rubber-bands while you orbit
- respect `env(safe-area-inset-*)` so controls clear the home indicator
- **no hover-dependent UI** — everything must work on tap
- big tap targets and high contrast; this gets used in shop light with dusty hands
- `navigator.wakeLock` (iOS 16.4+) so the screen doesn't sleep mid-part
- iOS Safari can evict script-writable storage — **export/import JSON is essential,
  not a nicety** (see §6)

---

## 3. Data export spec

Write a **new** script `export_assembly_json.py` in `Documents\RhinoScripts\`.
Read-only against the model — same discipline as `apply_numbering.py`. Reuse
`_np_helpers.py` for board matching (do not re-implement it — see the centroid trap
documented there).

Sources:
- GH component outputs: `P` (panels), `B` (plates), `A` (part-ID dots, index-aligned with `P`), `TB` (bevel table + joint schedule)
- `Final::FinalOutputFlat` — flat true-shape outlines
- `Final::FinalCNCBoard{1,2}` — **board outlines, used directly as the board map**
- `Final::FinalCNCBoard{1,2}Numbers` / `...Angles` — board position + mirror state per part

### Schema

```jsonc
{
  "meta": {
    "model": "260728_1zu200 Umgebungsgebäude.3dm",
    "units": "mm", "scale": "1:200", "thickness": 4.0,
    "machine": "disc sander, tilting table, 0-45 plus a 45 deg jig",
    "angleConvention": "shown = half fold; table = 90 - shown; flip if negative; jig above 45"
  },
  "buildings": [
    { "id": "1", "name": "Building 1", "partIds": ["1.1","1.2"], "bbox": [x0,y0,z0,x1,y1,z1] }
  ],
  "parts": [
    {
      "id": "1.1",
      "building": "1",
      "area": 4382.56,
      "mesh": { "v": [x,y,z, ...], "t": [i,j,k, ...] },   // world coords, 2 dp
      "flat": {
        "outline": [[x,y], ...],          // true shape, origin at its own bbox min
        "outerFaceUp": true               // +Z of the flat view is the building's OUTSIDE
      },
      "edges": [
        {
          "n": 0,
          "len": 27.38,
          "shown": 55,                    // what the GH flat layout prints (half fold)
          "set": 35,                      // what to dial on the sander table
          "flip": false,                  // flip the piece over first
          "jig": false,                   // use the 45 deg jig
          "label": "35",                  // matches the board Angles layer exactly
          "type": "miter",                // miter | flat | square
          "needsWork": true,              // false for the 296 already-square edges
          "mate": "1.4",                  // part it joins, or null
          "mateSet": 35,                  // the mating part's setting, for cross-checking
          "joint": 1,
          "flatSeg": [[x,y],[x,y]],       // this edge on the flat outline
          "seg3d": [[x,y,z],[x,y,z]]      // this edge in the assembled model
        }
      ],
      "board": { "sheet": "FinalCNCBoard1", "x": 953.0, "y": -983.1, "mirrored": false },
      "flags": ["fallback"]
    }
  ],
  "plates": [ { "id": "BP1", "mesh": {...}, "note": "outline was edited after nesting" } ],
  "boardMaps": {
    "FinalCNCBoard1": {
      "bbox": [x0,y0,x1,y1],
      "outlines": [ { "partId": "7.17", "pts": [[x,y], ...] }, ... ],
      "leftovers": [ { "pts": [[x,y], ...] }, ... ]      // the 11 X curves, greyed out
    }
  },
  "order": ["BP1","BP2","BP3","1.3","1.1", ...],
  "warnings": [
    "Parts 7.8, 7.9, 7.10 are not nested on either board and still have to be made.",
    "11 curves on the boards are leftovers from an earlier version - do not use them."
  ]
}
```

### Notes on generating it
- **Normalise IDs.** The fallback part's flat label is `7.11*` and the plates are
  `BP1?`/`BP2?`/`BP3?` on the boards. Strip `*` and `?` into `flags`, or the tool will
  treat `7.11` and `7.11*` as two parts. (My feasibility probe hit exactly this and
  briefly mis-reported 7.11 as unlocated when it is in fact on a board.)
- **`flip` must already account for mirroring.** In the flat layout +Z is the panel's
  OUTER face; a mirrored nest instance lies outer-face-down on the board, so the flip
  flag inverts. `apply_numbering.py` already XORs this — copy that logic.
- Round mesh coords to 2 dp. Halves the payload; 0.01 mm at 1:200 is 2 mm real.
- Keep `shown` even though it's redundant — it's what's printed on the existing flat
  layout, so it lets Niklas cross-check the tool against the drawing.

---

## 4. Assembly order

The joint graph is connected per building, so:

```
order = [base plates first]
for each building:
    seed = largest-area part whose min Z equals the building's min Z   # sits on the plate
    placed = {seed}
    while unplaced parts remain:
        pick the unplaced part with the MOST joints to already-placed parts
        tie-break: lower centroid Z first, then larger area
        append, mark placed
```

Ground-up, and every new piece always glues to something already standing — which is
what miters need, because you need the adjacent face to register against.

**Building order:** ascending part count (4-part buildings first), so the technique is
learned on simple boxes before building 6 (33 parts) and 7 (26 parts). Overridable.

Emit the order but let the user jump around freely — it's a guide, not a wizard.

---

## 5. UI spec

### Screen A — 3D model (the home screen, always reachable)
- Full-viewport 3D, orbit/pinch. Parts coloured by state: **raw** / **bevelled** / **glued**.
- **Tap any part → opens its card.** (raycasting)
- Filter to one building; ghost or hide the rest.
- Sidebar/sheet: building list with progress (`6/13`).

### Screen B — the part card (where the work happens)
Portrait-first, because this is the screen used on the phone.

- **3D, top and large.** This part highlighted; already-glued parts solid; the rest
  ghosted. Auto-framed on the part, still orbitable. This is the bit Niklas actually
  wants — *where does this piece go and which way round*.
- **Flat true shape** with every edge annotated: length, the sander label
  (`35`, `F25`, `J7`, `sq`), and the mating part id. Grey out the `sq` edges — they're
  already correct from the CNC and need nothing.
- **Outer-face indicator** — which side faces out. The flip flag is relative to it.
- **Where to find it**: board map (drawn from the `FinalCNCBoard` outlines) with this
  piece highlighted in place, leftovers greyed. No photo needed.
- **Mate check**: for each edge show the mating part's setting too. Both halves should
  sum to the fold angle — showing them together catches a mis-set table before glue.
- State buttons: **`bevelled ✓`** and **`glued ✓`**, independent.
- Free-text note per part.
- Prev / next along the assembly order.

### Screen C — setup batches (secondary)
Group remaining edges by sander setting. With a quick-adjust disc sander this is a
convenience, not the main event — 224 of 430 edges are at 45° so there's still an easy
win there, but the 44-setup long tail mostly has 2 edges each and isn't worth chasing.
Build this last, or skip it for v1.

---

## 6. Progress saving

- **Primary: `localStorage`**, keyed by model id + a data-version hash. Autosave on every tick.
- **iOS Safari can evict script-writable storage**, and `file://` storage is worse.
  So: **explicit `Export progress` → downloads a small JSON, and `Import progress` →
  file picker.** This is the real backup; localStorage is the convenience layer.
- Progress payload is just `{partId: {bevelled: bool, glued: bool, note: string}}` —
  a few KB, and it doubles as laptop↔phone sync since there's no server.
- Show "last saved", and warn visibly if storage is unavailable.
- Key progress by part **id**, never index, so a re-export doesn't scramble it. Warn if
  an imported file references ids that aren't in the loaded data.

---

## 7. Gotchas

- `fetch()` on `file://` — see §2.1.
- **The angle convention is settled** (`saw-bevel-angle-convention` memory): the number
  on the flat layout is half the fold angle, **table = 90 − shown**, flip if negative,
  45° jig above 45. The anchor is that 178 of 430 bevelled edges are at 45 = ordinary
  square corner = 45° on the machine. Don't re-derive it. Only the wording changes from
  "saw" to "sander table" — the 0–45 range and the jig were always about this machine.
- **7.8, 7.9, 7.10 are not on either board** and still have to be made. Surface loudly.
- **11 leftover curves** are milled into the boards from an earlier version — 7 cluster
  around (390…560, −900…−975) on Board 1. Draw them greyed and labelled on the board
  map, or someone picks one up and uses it.
- The 3 base plates were hand-edited after nesting, so their board outlines don't
  exactly match the model outlines. They're square-edged so nothing depends on it —
  just don't let a strict match check reject them.
- Part **7.11** is an unmitered fallback (a 6.5 mm² face too small to miter at T=4) —
  flag it so he doesn't hunt for a bevel that isn't there.
- 14 edges are type `flat` (fold ≈ 180°, setting ≈ 0). Treat as square/no-work.

---

## 8. What Niklas should supply

Very little — the tool can be generated from the model as it stands.

1. **Preferred build order** — default is ascending part count; say if you'd rather go
   geographically across the site.
2. **Any parts already bevelled or glued**, as a starting progress state.
3. Confirmation that **T = 4.0 mm** is the material actually used.
4. **Whether the repo can be public** (see §2.1 — free GitHub Pages requires it; if not,
   Cloudflare Pages or Netlify host from a private repo for free).

*(No board photos needed — the `FinalCNCBoard` outlines are already in the file and
serve as the board map directly.)*

---

## 9. Build steps

### Phase 1 — export (Rhino open, one sitting, then done)
1. Write `export_assembly_json.py` (read-only, reuses `_np_helpers.py`).
2. Run it and verify the counts before moving on: **138 panels + 3 plates, 726 edge
   rows, 430 with `needsWork: true`, 154 board outlines, 225 joints, 14 buildings.**
   If any of those are off, the data is wrong and everything downstream inherits it.
3. Implement the §4 order algorithm inside the same script; sanity-check that no
   building's sequence ever places a part with zero joints to the already-placed set.
4. Commit `assembly_data.js`. **Rhino is now done with.**

### Phase 2 — the tool (no Rhino)
5. Set up the repo per §2.1 and get a blank page live on Pages first — confirm the
   URL, Add to Home Screen, and the relative paths all work before writing features.
6. Build the 3D view first; it's the core. Get orbit + pinch + tap-to-select working
   on an actual iPhone before building anything else.
7. Then the part card, then progress, then the service worker, then (optionally)
   setup batches.
8. Verify against Rhino: pick 3 parts at random and confirm the tool's angles match
   `CutList_MiterAngles.txt` and the board `Angles` layer exactly.
9. Test progress properly: tick, close, reopen, export, wipe storage, import — on the
   phone, not just the laptop. Then turn wifi off and confirm it still loads.

---

## 10. Open questions

- Do the 3 base plates need part cards, or just a "glue everything to this" note?
- Should `glued` be per-part, or per-joint? Per-part is simpler; per-joint is more
  accurate for a part that meets four neighbours at different times.

## Related
- `MiterPanels_HANDOFF.md` — the tool that generated the parts, and the angle convention
- `CutList_MiterAngles.txt` — the current per-part cut list, this tool's text ancestor
- `apply_numbering.py` / `_np_helpers.py` — board matching, mirror handling
