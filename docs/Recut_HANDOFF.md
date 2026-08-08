# Recut Integration — Handoff

**Written 2026-08-07, after the tool was already built and pushed.**
This is a change to a **live page with real saved progress on Niklas's phone**. Read
§1 before touching anything — there are two traps that will silently destroy that
progress or serve stale data forever.

---

## 0. What happened

The nest was built from the **outer** outline of each panel (`FL` from the GH tool,
which at `M=0` is the original face outline). The per-edge setback is
`a = T / tan(bevel)`:

- **convex** corner (bevel < 90) → setback positive, inner face sets *back* → the outer
  outline **is** the true silhouette → nesting it was correct
- **reentrant** corner (bevel > 90) → setback **negative**, the inner face extends
  **past** the face outline → the blank had to be **bigger** than the face it came from

So **52 of 138 panels were milled undersize**, across 70 reentrant edges:

| shortfall | panels |
|---|---|
| ~4.0 mm (135° corners = full material thickness) | 42 |
| 3.6–4.35 mm | 6 |
| 2.99 mm — `2.12`, the one Niklas spotted | 1 |
| 0.18–0.46 mm — `11.1` `11.2` `6.21` `6.27`, sanding tolerance | 4 |

Worst are `6.6` and `6.7` at 4.35 mm. Building 6 is hit hardest (25 of its 33 parts),
then 7 (9), 2 (6), 5 (4), and pairs in 4, 8, 11, 14. **48 genuinely need re-cutting.**

Corrected silhouettes are already built in Rhino — see §4.

---

## 1. The two things that will break the live page

### 1a. `STORE_KEY` — this will wipe Niklas's progress

`index.html` currently has:

```js
const DATA_HASH = djb2([D.meta.model, D.meta.generated, PARTS.length, PLATES.length, ALL_WORK].join('|'));
const STORE_KEY = 'assemblyGuide.v1.' + DATA_HASH;
```

`D.meta.generated` is a **build timestamp**. Re-running the export changes it, which
changes `DATA_HASH`, which changes `STORE_KEY` — and every tick he has made becomes
orphaned under a key nothing reads. He will open the page in the workshop and find an
empty checklist.

**Fix, both halves:**

1. **Drop `generated` from the hash.** Key on what would actually invalidate progress —
   the set of part ids — not on when the file was built:
   ```js
   const DATA_HASH = djb2(PARTS.map(p => p.id).sort().join(',') + '|' + PLATES.length);
   ```
2. **Add a one-time migration** so the progress that already exists under the old hash
   survives this deploy. On load, if the new key has nothing, scan
   `Object.keys(localStorage)` for other `assemblyGuide.v1.*` entries, take the newest
   whose part ids are all present in the current data, adopt it, and immediately re-save
   under the new key. Log what it did so it is verifiable, and only ever do it when the
   new key is empty.

Do not skip (2) because (1) "fixes it going forward" — it does not recover what is
already stored under the timestamped key.

### 1b. `sw.js` — the phone will serve the old data forever

`sw.js` precaches `./assembly_data.js` under `const CACHE = 'assembly-guide-v1'` and
serves **cache-first**. The file's own comment says it: *"Bump CACHE when any precached
file changes — that is what triggers the update."*

**Bump it to `'assembly-guide-v2'`** in the same commit that changes `assembly_data.js`.
Without that, the installed home-screen app keeps the old data until the background
revalidate happens to win a race — which in a workshop with bad wifi may be never.

After deploying, verify on the phone: it must show the new recut banner, not the old
part count.

---

## 2. Data changes — `rhino/export_assembly_json.py`

Keep the existing shape. Everything below is **additive** except `flat.outline`, which
changes *values* only. `index.html` ignores fields it does not know, so a data deploy
ahead of the UI deploy is safe.

### 2a. `parts[].flat.outline` → the true silhouette

Replace the face outline with the silhouette of the solid seen along the face normal.
For the 86 unaffected parts this is byte-identical; for the 52 it is bigger.

**The one thing to get right:** the outline and the edge segments share an origin.
In the current code:

```python
a2(r["outline"], r["min"])          # outline, offset by r["min"]
edge_js(e, mn)  ->  p.X - mn.X      # flatSeg, offset by the same mn
```

The silhouette has a **different bbox min** from the face outline. So when you replace
`r["outline"]`, you must recompute `r["min"]` from the silhouette and pass that same
value into `edge_js`. If you change one and not the other, every edge label on the part
card detaches from its edge — and it will look plausible, not broken, which is worse.

Method (matches what produced the Rhino layer, exact for planar-faced solids):

```python
m = Mesh.CreateFromBrep(panel, MeshingParameters.Default)   # append the pieces
m.Weld(math.radians(180))
outs = m.GetOutlines(Plane(capOrigin, capOutwardNormal))    # take the largest closed one
```

### 2b. New per-part fields

```jsonc
"flat": {
  "outline": [...],            // now the silhouette
  "milledOutline": [[x,y],...],// ONLY for undersize parts: what was actually milled,
                               // same origin as outline, so the card can hatch the gap
  "outerFaceUp": true
},
"blank": {                     // omit entirely for parts that are fine
  "status": "undersize",
  "shortBy": 4.35,             // mm, max over the part's reentrant edges
  "ignorable": false,          // true for the four under 0.5 mm
  "edges": [1],                // edge indices responsible
  "sheet": "Recut", "x": 123.4, "y": 2712.0, "mirrored": false
},
"flags": ["undersize"]         // append to the existing list, don't replace it
```

`parts[].board` **stays exactly as it is** — it is where the piece was originally
milled, and the tool needs it to tell him that piece is scrap. Do not repoint it at the
recut sheet; `index.html` reads `board.` in nine places.

### 2c. Third board map

`boardMaps` is a dict keyed by sheet name with entries
`{bbox, sheet, outlines:[{partId,pts}], leftovers:[{pts}], marks:[{pts}]}`.
Add a `"Recut"` key in **exactly that shape** and the existing board-map renderer draws
it with no changes:

```jsonc
"boardMaps": {
  "FinalCNCBoard1": {...},
  "FinalCNCBoard2": {...},
  "Recut": { "bbox":[0,2600,837,2890], "sheet":null,
             "outlines":[{"partId":"6.7","pts":[...]}, ...], "leftovers":[], "marks":[] }
}
```

Read this from the baked Rhino layers (§4), the same way the other two board maps are
read — that layout is what he will actually machine, so it must come from the geometry,
not be re-packed by the exporter.

### 2d. `meta` and `warnings`

```jsonc
"meta": { ..., "recut": { "parts": 52, "needed": 48, "ignorable": 4,
                          "blockW": 837, "blockH": 290, "areaMm2": 79277 } }
```

Prepend to `warnings`: *"52 panels were milled undersize because the nest used the face
outline instead of the miter silhouette. 48 need re-cutting from the Recut sheet; the
originals are scrap."*

---

## 3. UI changes — `index.html`

1. **Part card banner** when `flags` includes `undersize`: *"The piece on
   FinalCNCBoard1 is UNDERSIZE by 4.35 mm — do not use it. Cut a new one from the Recut
   sheet."* For `blank.ignorable` parts soften it to a note — 0.18 mm sands away.
2. **Draw `milledOutline` dashed inside `outline`, and hatch between them.** This is the
   single most useful thing in the whole change: he sees exactly which strip is missing
   and on which edge. Everything else is bookkeeping.
3. **Board map** on the card should default to the **Recut** sheet for undersize parts,
   with a toggle back to the original sheet showing that outline greyed and labelled
   *scrap*.
4. **Model screen filter**: "needs re-cut (48)", highlighting those parts in the 3D
   view. This is what the 3D view is for — he can see at a glance that building 6 is
   most of the problem.
5. **Progress**: add `recut: bool` to the progress record, shown only for undersize
   parts, and gate the `bevelled` tick behind it. Old saved progress simply lacks the
   key → falsy → correct default. Do not restructure the progress object beyond adding
   this key.
6. `KINDCOL` — add an entry for the recut state so it reads distinctly in the 3D view.

**Leave `STALE_BOARD` and `STALE_NONE` alone.** They are hardcoded part-id arrays about
baked-vs-live angle dots, unrelated to this, and unaffected by the recut.

---

## 4. Where the recut geometry is

Already built in the Rhino document, additive, nothing else touched:

- **`Recut::Outlines`** — 52 closed curves, magenta, the true silhouettes
- **`Recut::Labels`** — 52 TextDots with the part ids
- laid out at **(0, 2600)**, packed to 850 mm wide, block is **837 × 290 mm**
- total part area **79 277 mm² = 0.08 m²** — a small offcut, not a new board
- laid out **outer face up**, same convention as the original flat layout, so the
  existing angle labels and flip logic apply unchanged

Reports in `Documents\RhinoScripts\`: `Undersized_Panels_REPORT.txt` (per-part
shortfall, which edges, which mate) and `Recut_Sheet_REPORT.txt` (machined vs true area).

The 52 outlines are keyed to parts by the label dots, so match them the same way
`_np_helpers.py` matches the other boards — or more simply, read the label dot inside
each curve, since these were placed by us and are reliable.

---

## 5. Do NOT fix the root cause in this pass

The underlying bug is in `rhino/MiterPanels.py` — the GH component's `FL` output emits
the outer outline rather than the silhouette. **Leave it.** Changing it re-solves the
definition, which shifts the flat layout, which invalidates the board matching and every
part number and angle label already milled onto the boards and baked into
`Final::FinalTextDots`. Fix it only when the model is next regenerated from scratch, and
note it in `MiterPanels_HANDOFF.md` as a known issue.

---

## 6. Order of operations

1. Change the `DATA_HASH` / `STORE_KEY` logic and add the migration. **Deploy and verify
   on the phone that existing progress survives, before touching the data.** If you do
   this together with the data change and progress vanishes, you will not know which
   change caused it.
2. Update `export_assembly_json.py`, regenerate `assembly_data.js`.
3. Bump `CACHE` in `sw.js` to `'assembly-guide-v2'` in the same commit.
4. UI changes.
5. Deploy, then hard-verify on the phone (§7).

---

## 7. Verification

- `parts.length` still **138**, `plates.length` still **3**, `order.length` still **141**
- exactly **52** parts have `flags` containing `undersize`; **4** have `blank.ignorable`
- `boardMaps` has **3** keys; `boardMaps.Recut.outlines.length === 52`
- for a part with no reentrant edge (e.g. `1.1`), `flat.outline` is **unchanged** from
  the current deployed data — diff it, this proves you did not disturb the other 86
- for `2.12`: `blank.shortBy ≈ 2.99`, and `milledOutline` is visibly inside `outline`
- pick 3 undersize parts and confirm every `flatSeg` still lands on the drawn outline —
  this is the §2a trap
- **on the phone:** progress from before the deploy is still there, the new banner shows,
  and it still works with wifi off
