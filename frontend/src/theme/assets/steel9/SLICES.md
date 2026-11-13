# Steel v9 housing — slice map

Production slices for the Steel theme's generated-artwork housing frame,
cut from the owner-approved v9 masters (masters live outside the repo in
`~/workspace/goals/toolbox-vault-website/files/steel-art/` and are NOT
modified by this process):

- Landscape master: `steel-frame-v9-landscape.webp`, 2048×1152
- Portrait master: `steel-frame-v9-portrait.webp`, 1152×2048

## Trim (first step for both masters)

Each master carries a pure-black margin. Slices are cut from the trimmed
frame only; all rectangles below are in **trimmed coordinates**
(x0, y0, x1, y1), WebP quality 82, full resolution (no downscale — the
dark art compresses small).

| Master    | Trim box in master coords | Trimmed size |
|-----------|---------------------------|--------------|
| Landscape | (165, 86) → (1886, 1073)  | 1721×987     |
| Portrait  | (112, 123) → (1040, 1931) | 928×1808     |

Rail cross-sections in the art: landscape top/bottom rails are 150 deep,
side rails 175 wide; portrait top/bottom rails are 160 deep, side rails
145 wide. Corner crops are exactly those cross-sections, so pieces butt
with no overlap and no missing art (runs start where corners end).

## Landscape slices (prefix `l-`)

| File                 | Source rect (trimmed)   | Contents |
|----------------------|-------------------------|----------|
| l-corner-tl.webp     | (0, 0, 175, 150)        | top-left chamfered corner |
| l-corner-tr.webp     | mirror of l-corner-tl   | top-right corner |
| l-corner-bl.webp     | (0, 837, 175, 987)      | bottom-left corner |
| l-corner-br.webp     | mirror of l-corner-bl   | bottom-right corner |
| l-top-run.webp       | (175, 0, 470, 150)      | top rail straight run (stretches; used both sides of center) |
| l-bottom-run.webp    | (175, 837, 470, 987)    | bottom rail straight run |
| l-top-center.webp    | (620, 0, 1100, 150)     | top-center trapezoid + glow + perforation row (fixed size, never stretched) |
| l-bottom-center.webp | (620, 837, 1100, 987)   | bottom-center trapezoid + glow |
| l-side-run-t.webp    | (0, 150, 175, 320)      | left rail upper run (stretches) |
| l-side-run-tr.webp   | mirror of l-side-run-t  | right rail upper run |
| l-side-run-b.webp    | (0, 667, 175, 837)      | left rail lower run |
| l-side-run-br.webp   | mirror of l-side-run-b  | right rail lower run |
| l-side-center.webp   | (0, 360, 300, 640)      | left light channel + vents + bloom spill into the well (wider than the rail on purpose) |
| l-side-center-r.webp | mirror of l-side-center | right light channel |

## Portrait slices (prefix `p-`)

| File                 | Source rect (trimmed)   | Contents |
|----------------------|-------------------------|----------|
| p-corner-tl.webp     | (0, 0, 145, 160)        | top-left chamfered corner |
| p-corner-tr.webp     | mirror of p-corner-tl   | top-right corner |
| p-corner-bl.webp     | (0, 1648, 145, 1808)    | bottom-left corner |
| p-corner-br.webp     | mirror of p-corner-bl   | bottom-right corner |
| p-top-run.webp       | (145, 0, 265, 160)      | top rail straight run |
| p-bottom-run.webp    | (145, 1648, 265, 1808)  | bottom rail straight run |
| p-top-center.webp    | (270, 0, 660, 160)      | top-center trapezoid + glow + perforations |
| p-bottom-center.webp | (270, 1648, 660, 1808)  | bottom-center trapezoid + glow |
| p-side-run-t.webp    | (0, 160, 145, 330)      | left rail upper run |
| p-side-run-tr.webp   | mirror of p-side-run-t  | right rail upper run |
| p-side-run-b.webp    | (0, 1478, 145, 1648)    | left rail lower run |
| p-side-run-br.webp   | mirror of p-side-run-b  | right rail lower run |
| p-side-center.webp   | (0, 700, 260, 1110)     | left light channel + bloom spill |
| p-side-center-r.webp | mirror of p-side-center | right light channel |

## Interior grain tile

| File       | Source | Process |
|------------|--------|---------|
| grain.webp | **Panel master** (below), trimmed rect (800, 600, 1312, 1112) — a 512×512 well window chosen by scan as the calmest region (lowest low-frequency variance, no perforation clusters) | 48px mirror cross-fade on all edges for seamless tiling; tone normalized to the shipped tile's tuning (mean ≈ 30, std ≈ 4.8) so no surface brightness shifted. Resampled 2026-10-17 from the panel master's well so the interior surfaces are literally the panel's own material (one material family, interior = exterior). The previous tile came from the landscape housing master's plate; tones matched within ~2 luminance points, the resample is for material provenance, not a visible fix. |

## Totals

29 files, **106.3 KB** total (budget was ~500 KB). Display geometry
(aspect factors, rail sizes, glow anchors) lives in
`../../surfaces.css` (`.tv-housing*`) and `../../themes/steel.css`
(`--housing-*` tokens).

---

# Component art kit (added 2026-10-17)

Sliced from the two component masters (same art family as the housing;
masters outside the repo in `~/workspace/goals/toolbox-vault-website/files/steel-art/`,
never modified):

- Panel master: `steel-panel-master.webp`, 1792×1344 — thin chamfered
  frame, blank brushed-chrome nameplate header row, vertical-grain well,
  perforation clusters at the well corners, center trapezoid notch in
  the bottom rail. NO glow anywhere (by design law).
- Nameplate master: `steel-nameplate-master.webp`, 4480×560 — wide
  chrome plate, chamfered end caps, black channel lines, one DARK unlit
  socket near each end. NO glow.

Trims (black margins removed): panel (98, 60) → (1693, 1286) = 1595×1226;
nameplate (143, 60) → (4337, 500) = 4194×440 (rows below y=440 in the
bbox were pure black). All rects below are trimmed coords, WebP q84.

## Panel kit (prefix `pk-`) — responsive thin-wall display (see --pk-* tokens)

Rendered geometry is NOT the masters' proportions (owner rule: thin
walls, maximized interior). All display sizes are clamp()s in
themes/steel.css: side rail 6px @390w → 10px max, bottom rail 7→10px,
header band 28→34px, notch piece 48→76px wide. Corners fixed, edges
stretch; art only ever downscales. Kit image files are referenced ONLY
through the --pk-*/--np-* source variables in steel.css, so a future
asset swap re-points variables and touches nothing else.

Cross-sections: header block y 0..200 (top rail + chrome band +
separator + groove), frame side 88 wide, bottom block y 1120..1226.

| File          | Source rect (trimmed)     | Role in the CSS construction |
|---------------|---------------------------|------------------------------|
| pk-hl.webp    | (0, 0, 88, 200)           | header row left cap + TL corner |
| pk-hm.webp    | (700, 0, 900, 200)        | header row stretch |
| pk-hr.webp    | (1507, 0, 1595, 200)      | header row right cap + TR corner |
| pk-tl.webp    | (0, 0, 88, 34)            | headerless top-left corner (top rail strip) |
| pk-tm.webp    | (700, 0, 900, 34)         | headerless top run |
| pk-tr.webp    | (1507, 0, 1595, 34)       | headerless top-right corner |
| pk-el.webp    | (0, 700, 88, 1000)        | left edge (plain rail section, below the rail notch detail; stretches vertically) |
| pk-er.webp    | (1507, 700, 1595, 1000)   | right edge |
| pk-bl.webp    | (0, 1120, 88, 1226)       | bottom-left corner |
| pk-br.webp    | (1507, 1120, 1595, 1226)  | bottom-right corner |
| pk-blrun.webp | (200, 1120, 420, 1226)    | bottom run, left of notch (stretches) |
| pk-brun.webp  | (1180, 1120, 1400, 1226)  | bottom run, right of notch (stretches) |
| pk-bm.webp    | (420, 1120, 1180, 1226)   | bottom CENTER notch piece (760×106 source; displayed at --pk-notch-w, never stretched) |

13 files, 35.4 KB. The well behind the frame is `grain.webp` (above).
The master's well-corner perforation clusters sit below the header
block (y > 200) and are NOT reproduced per-panel — they belong to the
master's fixed composition, not to arbitrary panel sizes.

## Nameplate kit (prefix `np-`)

Socket centers were located by dark-disc scan (disc mean vs ring mean):
**(390, 205)** and **(3800, 205)** trimmed — symmetric, 390/394px from
the outer edges; each cap piece is 640 wide so the socket sits 250/246px
from the cap's inner edge. In the app header (cap displayed 84px wide)
the glow dots anchor at 0.6094 / 0.6156 of cap width (steel.css).
Pieces were downscaled to 220 tall after slicing (display ≈ 58px →
~3.8× headroom); np-mid also narrowed to 550 (it only ever stretches).

| File       | Source rect (trimmed)   | Contents |
|------------|-------------------------|----------|
| np-l.webp  | (0, 0, 640, 440)        | left cap WITH dark socket |
| np-mid.webp | (1500, 0, 2600, 440)   | center stretch (calm field, right of the sheen peak) |
| np-r.webp  | (3554, 0, 4194, 440)    | right cap WITH dark socket |

3 files, 48.7 KB. np-mid also serves (stretched) as table-header,
secondary-button and nav-plate material in steel.css.

## Housing center neutralization (2026-10-17)

The housing center slices shipped with AMBER light baked into the art,
which fought the live accent (top/bottom lights stayed amber under a
blue accent). Transform, applied in place to all 8 center files
(`l-/p-` top-center, bottom-center, side-center, side-center-r):

```
lum = mean(R, G, B)                       # per pixel
w   = max(0, R - B)                       # warmth
s   = 1 / (1 + w / 18)                    # saturation scale
out = lum + (rgb - lum) * s               # hue pulled to neutral,
                                          # luminance/shape untouched
```

Saved WebP q92. Measured warmth (R−B), before → after:

| File | mean all | brightest 1% core | bloom band (75th–99th pct lum) |
|------|----------|-------------------|--------------------------------|
| l-top-center | 34.3 → 9.3 | 5.6 → 3.4 | 28.5 → 8.7 |
| l-bottom-center | 33.7 → 8.9 | 5.0 → 3.4 | 48.2 → 10.9 |
| p-top-center | 29.4 → 8.4 | 13.8 → 6.8 | 33.2 → 7.7 |
| p-bottom-center | 25.8 → 7.5 | 8.9 → 5.1 | 43.2 → 9.6 |
| l-side-center (×2) | 33.6 → 9.9 | 10.4 → 6.1 | 57.9 → 11.7 |
| p-side-center (×2) | 34.1 → 9.7 | 14.8 → 7.4 | 56.8 → 11.1 |

The visible amber lived in the bloom band (28–58 warmth) — cut 4–5×.
Cores were already near-white and are now neutral (3–7). Residual mean
warmth (~8–10) is the warm-lit brushed metal itself, not the light;
with the cores neutral, the screen-blended accent overlays (raised to
0.72 opacity top/bottom in surfaces.css) own the lights' color.
Metal/socket geometry is untouched (luminance preserved per pixel).


---

# Variant kits (2026-10-17) — app-style, derived, and Emergent-spec

Sliced by `/tmp/slice_app.py` + `/tmp/slice_spec.py` (PIL). All kits use
the SAME slot names as the silver kit above (`pk-*`, `np-*`, housing
`l-*`/`p-*`), so variants swap purely by CSS variable assignment
(themes/steel.css shared construction; per-variant files steel1–5/7/8).
IMPORTANT: the generated masters have noisy near-black backdrops
(~85-luminance speckle), so trims were pinned from luminance PROFILES,
not thresholds. Verified object boxes:

| master | box (x0,y0)→(x1,y1) | trimmed |
|---|---|---|
| steel-housing-appstyle.webp | (243,75)→(1806,1074) | 1563×999 |
| steel-housing-appstyle-portrait.webp | (118,123)→(1035,1925) | 917×1802 |
| steel-panel-appstyle.webp | (232,88)→(1572,1218) | 1340×1130 |
| steel-nameplate-dark.webp | (99,59)→(4832,447) | 4733×388 |
| steel-buttonplate.webp | (210,35)→(4285,525) | 4075×490 |
| steel-inputstrip.webp | (188,76)→(4288,488) | 4100×412 |
| steel-panel-spec.webp | (85,77)→(1834,1203) | 1749×1126 |

## assets/steelapp/ — app-style kit (Steel REDO, 1, 2-housing, 4-housing)

Housing (same slot mapping as silver; surfaces `--h-img-*` names):
corners = sideW×topD; landscape topD 168, sideW 164, centers 469 wide,
side centers 254×300 (spill 90); portrait topD 130, sideW 96, centers
330 wide, side centers 149×306. Aspect factors — landscape:
`--h-top-center-f 2.7917, --h-side-center-wf 1.5488, --h-side-center-hf
1.8293`; portrait: `2.5385 / 1.5521 / 3.1875`. NOTE: `-run-l/-run-r`
and `-side-l-*/-side-r-*` files exist per side; surfaces vars take
top-run ← `l-top-run-l`, bottom-run ← `l-bottom-run-l`, side-run-t ←
`l-side-l-t`, side-run-tr ← `l-side-r-t`, side-run-b ← `l-side-l-b`,
side-run-br ← `l-side-r-b`, side-center ← `l-side-center-l`.

Panel kit (trimmed coords): sideW 74, header block 209, bottom block
130, headerless rail 44, edges y 542..768. `pk-hl/hr` = (0,0,74,209) /
(1266,0,1340,209); `pk-hm` x 536..804; `pk-t*` top 44 rows; `pk-bm`
x 449..891 of the bottom block; runs x 188..402 / 938..1152.

Dark nameplate: caps 700 wide (of 4733), pieces downscaled to 220 tall
(silver convention); mid x 1988..2745. Hex-bolt centers at trimmed
(250, ·) → header glow-dot seat fractions `--np-dot-lf/--np-dot-rf =
0.3571`, dot size 10px (vs silver sockets 0.6094/0.6156, 15px).

Button plate: caps 780 wide (bolts at trimmed x≈380 / W−380), mid
x 1549..2527; all pieces downscaled to 170 tall. `btn-*` = color
(sliced for the record; NOT used as faces — baked orange can't follow
the wheel). `btng-*` = grayscale twin (luminance, mean re-centered to
132 for overlay blend) — `btng-m.webp` is the wired asset
(--btn-plate-art, overlay-blended over the live accent plate).

Input strip: caps 560 wide, mid x 1640..2460, pieces at 160 tall;
wired via --in-l/--in-m/--in-r with --in-cap-w 30px, --input-pad-l
2.7rem (shared input construction in themes/steel.css).

Tiles: `grain-app.webp` 512² (panel-master well sample, mirror-fade,
gaussian-flattened, mean ≈27). Diamond plate: master flattened
(divide by σ140 blur), wrap-blend tileable, 768² — `field-dp.webp`
(full), `field-dp-dim.webp` (×0.40), `field-dp-dark.webp` (×0.20),
`grain-dp.webp` 640² (×0.30, panel emboss). `wear.webp` /
`wear-strong.webp` 640² tileable wear (PIL intermediates; wear reaches
CSS only pre-baked into the worn kit/tiles).

## Derived kits (PIL treatments of the app kit)

- `assets/steeldark/` (Steel 2): pk-* + np-* at brightness 0.60 /
  contrast 1.07; `grain-dark.webp` = grain-app ×0.55, contrast 1.10.
- `assets/steelworn/` (Steel 4): pk-* + np-* overlay-blended with the
  wear tile at 0.55 + warm shift (R×1.03, B×0.97); `grain-worn.webp`
  (0.6 blend), `field-worn.webp` (DP ×0.5 + wear 0.5).
- `assets/steel5/` (Steel 5): `grain-clean.webp` = silver grain at
  0.72 contrast around its mean + 0.5px blur (flattened stock).

## assets/steel7/ + assets/steel8/ — Emergent-spec kit (Steel 7/8)

Master `steel-panel-spec.webp`: a uniform double-border frame (outer
gunmetal border, DARK recessed channel — the live --accent inlay ring
seats there via CSS, never baked — inner lip, hollow well), hex bolt
inside each corner (trimmed ≈ (95,98) etc.). Frame cross-section 118;
corner blocks 170². The kit is frame-only: `--pk-hl/hr/hm` alias the
`pk-tl/tr/tm` files because Steel 7/8 recompose panel headers inside
the frame (stencil title + live rail) instead of stretching a band.
Steel 8 = the same slices PIL-cleaned (blur-blend 0.30 @1.4px,
brightness 1.24, contrast 1.06, saturation 0.92). Field:
`steel7/field-gears.webp` 1920×960 (composed background, `cover`,
shared by 7+8). `grain-spec.webp` 512² from the spec well.

Manifest (Emergent style — src / w / h / capInsets; capInsets are the
pieces' non-stretch guard bands as used by the shared construction):

```json
[
  {"src": "steel7/pk-tl.webp", "w": 170, "h": 170, "capInsets": {"top": 24, "left": 24, "bottom": 24, "right": 24}},
  {"src": "steel7/pk-tr.webp", "w": 170, "h": 170, "capInsets": {"top": 24, "left": 24, "bottom": 24, "right": 24}},
  {"src": "steel7/pk-tm.webp", "w": 629, "h": 118, "capInsets": {"top": 24, "left": 24, "bottom": 24, "right": 24}},
  {"src": "steel7/pk-el.webp", "w": 118, "h": 270, "capInsets": {"top": 24, "left": 24, "bottom": 24, "right": 24}},
  {"src": "steel7/pk-er.webp", "w": 118, "h": 270, "capInsets": {"top": 24, "left": 24, "bottom": 24, "right": 24}},
  {"src": "steel7/pk-bl.webp", "w": 170, "h": 170, "capInsets": {"top": 24, "left": 24, "bottom": 24, "right": 24}},
  {"src": "steel7/pk-br.webp", "w": 170, "h": 170, "capInsets": {"top": 24, "left": 24, "bottom": 24, "right": 24}},
  {"src": "steel7/pk-blrun.webp", "w": 350, "h": 118, "capInsets": {"top": 24, "left": 24, "bottom": 24, "right": 24}},
  {"src": "steel7/pk-brun.webp", "w": 350, "h": 118, "capInsets": {"top": 24, "left": 24, "bottom": 24, "right": 24}},
  {"src": "steel7/pk-bm.webp", "w": 419, "h": 118, "capInsets": {"top": 24, "left": 24, "bottom": 24, "right": 24}},
  {"src": "steel7/grain-spec.webp", "w": 512, "h": 512, "capInsets": {"top": 0, "left": 0, "bottom": 0, "right": 0}},
  {"src": "steel7/field-gears.webp", "w": 1920, "h": 960, "capInsets": {"top": 0, "left": 0, "bottom": 0, "right": 0}},
  {"src": "steel8/pk-tl.webp", "w": 170, "h": 170, "capInsets": {"top": 24, "left": 24, "bottom": 24, "right": 24}},
  {"src": "steel8/pk-tr.webp", "w": 170, "h": 170, "capInsets": {"top": 24, "left": 24, "bottom": 24, "right": 24}},
  {"src": "steel8/pk-tm.webp", "w": 629, "h": 118, "capInsets": {"top": 24, "left": 24, "bottom": 24, "right": 24}},
  {"src": "steel8/pk-el.webp", "w": 118, "h": 270, "capInsets": {"top": 24, "left": 24, "bottom": 24, "right": 24}},
  {"src": "steel8/pk-er.webp", "w": 118, "h": 270, "capInsets": {"top": 24, "left": 24, "bottom": 24, "right": 24}},
  {"src": "steel8/pk-bl.webp", "w": 170, "h": 170, "capInsets": {"top": 24, "left": 24, "bottom": 24, "right": 24}},
  {"src": "steel8/pk-br.webp", "w": 170, "h": 170, "capInsets": {"top": 24, "left": 24, "bottom": 24, "right": 24}},
  {"src": "steel8/pk-blrun.webp", "w": 350, "h": 118, "capInsets": {"top": 24, "left": 24, "bottom": 24, "right": 24}},
  {"src": "steel8/pk-brun.webp", "w": 350, "h": 118, "capInsets": {"top": 24, "left": 24, "bottom": 24, "right": 24}},
  {"src": "steel8/pk-bm.webp", "w": 419, "h": 118, "capInsets": {"top": 24, "left": 24, "bottom": 24, "right": 24}},
  {"src": "steel8/grain-spec.webp", "w": 512, "h": 512, "capInsets": {"top": 0, "left": 0, "bottom": 0, "right": 0}}
]
```

---

# Steel 9 — "Forged Vault" (assets/steelforged/)

Source spec: the owner's ChatGPT prompt ("FORGED INDUSTRIAL VAULT
UI") — silver carries structure, orange stays reserved, content
surfaces stay quiet. Kit = the app kit PIL-derived (same slot names)
+ two new tiles from a new master. Folder named `steelforged/` (the
`steel9/` folder is the silver kit; the theme id is steel9).

## Forged master taming

Master `steel-forged.webp` (outside repo, files/steel-art/), 1600² —
hammered forged black steel, generated too bright/busy: luminance
mean 39.0 / std 38.8, p95 125, with a hard directional falloff
(hotspot top-left, crushed bottom-right) and oversized dimples.

Pipeline (`/tmp/forge.py`, PIL + numpy):
1. Crop an 800² mid-tone window (400,300)→(1200,1100).
2. Gaussian-flatten: divide by the shared-luminance blur (σ100),
   rescale to the blur mean — removes the falloff and the big dimple
   shading; saturation pulled 62% toward neutral graphite.
3. Seamless via HALF-OFFSET BLEND (out = w·F + (1−w)·roll(F, ½),
   w = sin² windows, 1 at center / 0 at edges). A mirror super-tile
   was tried first and REJECTED: its mirror axes read as kaleidoscope
   medallions at panel sizes. The offset blend has no symmetry; the
   wrap step is bounded by the texture's own 1px gradient (worst
   single-pixel step on the shipped field tile ≈ 47 luminance at one
   hard dimple edge pre-veil, mean 1px gradient 2.2 — invisible under
   the production veil; the 2×2 tiling composite shows no boundary).
4. Tone-map per use:
   - `field-forged.webp` 768² → mean 39.5 / std 10.9 (p5 27, p95 61).
     Deployed as the page field under Steel 9's strong veil
     (0.60–0.76 black gradient + 9% accent wash) → effective field
     sits at ~10–16 luminance with the forged character legible at
     page margins.
   - `grain-forged.webp` 512² → mean 23.5 / std 3.3 (p5 20, p95 30).
     The panel-well / grain stock: the family's lowest-contrast
     texture (silver grain ships std 4.8) at a larger feature scale
     (~40px dimples) — a matte undulation, judged in composite
     against sample data rows: text stays on near-black everywhere
     (range 20–30), so Steel 9 did NOT need the calm-grain fallback.

## Derived kit (PIL treatment of assets/steelapp/)

Overlay-blend of the normalized forged luminance (z-scores, slight
steel tint B×1.07/R×0.94) over each app-kit piece, composited at low
alpha, then a small brightness trim — the steeldark/steelworn pattern:

- `pk-*` (13) + `np-*` (3) + `in-*` (3): alpha 0.30, brightness 0.95.
- Housing `l-*`/`p-*` (32): alpha 0.20, brightness 0.97 — the forged
  character at whisper level on the frame plates; geometry, sockets
  and aspect factors are the app housing's, unchanged (landscape
  2.7917 / 1.5488 / 1.8293; portrait 2.5385 / 1.5521 / 3.1875).

53 files total (2 tiles + 51 derived), 198.3 KB. Manifest:

```json
[
  {"src": "steelforged/field-forged.webp", "w": 768, "h": 768, "capInsets": {"top": 0, "left": 0, "bottom": 0, "right": 0}},
  {"src": "steelforged/grain-forged.webp", "w": 512, "h": 512, "capInsets": {"top": 0, "left": 0, "bottom": 0, "right": 0}},
  {"src": "steelforged/pk-* + np-* + in-* (19 files)", "note": "same dims/capInsets as the steelapp originals"},
  {"src": "steelforged/l-* + p-* (32 files)", "note": "same dims/capInsets as the steelapp housing originals"}
]
```

---

# Steel 4 refinement — chamfered kit (assets/steelworn2/)

Steel 4 ("Worn Workhorse") was chosen as THE Steel direction
(2026-10-17) and refined per the owner's four adjustments. The
shared panel construction in themes/steel.css is untouched: Steel 4
carries a scoped construction in themes/steel4.css built on this
new kit. Derivation script: `/tmp/derive_worn2.py` (PIL); QA
composites: `/tmp/composite4.py` → `/tmp/steel4qa/`.

## Lightening (adjustment 1) — measured

Recipe = the steelworn recipe (wear overlay-blend + warm shift)
followed by a per-category GAIN stage. Mean luminance (Rec. 709),
shipped steelworn → steelworn2:

| Stock | Before | After | Δ |
|---|---|---|---|
| Well grain (`grain-worn` → `grain-worn2`) | 28.0 | 33.1 | +18% |
| Frame stock (`pk-hm`) | 43.8 | 51.7 | +18% |
| Nameplate mid (`np-m`) | 60.8 | 71.3 | +17% |
| Nameplate cap (`np-l`) | 21.8 | 25.4 | +17% |

Surface tokens in steel4.css lifted to match (--panel #12100e →
#161310 ≈ +19% luminance; --surface, --surface-raised, --edge,
--table-row-hover similarly ~+16–23%). Text tokens unchanged —
contrast preserved.

## Chamfered panel kit (adjustment 2)

Source = the app panel master (trimmed 1340×1130; trim offset
(232, 88) in the 1792×1344 master). The master's own silhouette is
an elongated octagon (45° corner legs ≈ 45 source px): corner
alpha is EXTRACTED from that silhouette (lum > 16 mask, cleaned,
feathered 1.1px), and steel4.css clips the panel box itself with a
matching polygon (--pk4-cut ≈ 0.18 × corner width at every clamp),
so the cut is real — field shows through, border/shadow/art clip
together.

Display geometry (steel4.css tokens; rails stay the family
--pk-sw / --pk-th thin-wall values):
--pk4-cw clamp(30px, 4.2vw, 42px) corner gusset width;
--pk4-td clamp(15px, 2.1vw, 21px) headerless top zone;
--pk4-bd clamp(19px, 2.7vw, 27px) bottom zone;
--pk4-nw clamp(64px, 10vw, 96px) center step width, capped per
panel via min() (--pk4-nwe 36% top/bottom, --pk4-nwe2 40% header);
--pk4-tab clamp(6px, 1vw, 9px) header step tab drop.

| File | Source / synthesis | Display role |
|---|---|---|
| pk4-hl/hr.webp | master (0,0,260,209) + silhouette alpha (hr = mirror) | header band caps, chamfer + bolt |
| pk4-hm.webp | master (536,0,804,209) | header band runs (×2 around center) |
| pk4-hc.webp | synthesized 384×172 @4×: band (top 136) + trapezoid tab below (transparent elsewhere), dark socket at (192,153) r21 | header CENTER step, fixed |
| pk4-tl/tr.webp | master (0,0,260,130) + silhouette alpha | headerless top gussets |
| pk4-tm.webp | master (536,0,804,44) | top rim runs |
| pk4-tc.webp | synthesized 384×84 @4×: rim (top 28) + trapezoid step down, socket (192,60) r20 | headerless top CENTER step, fixed |
| pk4-el/er.webp | master (0,542,74,768) / (1266,542,1340,768) | side rails |
| pk4-bl/br.webp | master (0,970,260,1130) + silhouette alpha | bottom gussets, chamfer + bolt |
| pk4-blrun/brun.webp | master (188,1000,402,1130) / (938,1000,1152,1130) | bottom runs |
| pk4-bm.webp | synthesized 384×108 @4×: bottom band + trapezoid step UP, bright top edge, socket (192,34) r21 | bottom CENTER step, fixed |
| pk4-np-l/m/r.webp | steelapp np pieces, wear α 0.70 + gain 1.15 | nameplate (header/table/button stock) |
| grain-worn2.webp | grain-app, wear α 0.6, gain to mean 33.1 | panel well |
| btnwear.webp | owner's steel-wear-overlay.webp master: 800² window, offset-blend seamless, recentered mean 128 / std ≈ 34, 448² q72 | CSS wear layer for metal buttons |

20 files, 230 KB. (Heavier than steelworn's ~85 KB: corner pieces
are 260-wide with alpha, centers are 4× syntheses, and the button
wear tile is photographic noise — the lazy-load pass owed family-
wide covers this too.)

## Per-panel illumination (adjustment 3)

- Title dot: steel4.css lights `.tv-panel-title::before` on ALL
  headered panels + `.tv-modal-title::before` (shared machinery
  lights plate-variant panels only) — the unified --glow-dot-*
  treatment.
- Step dots: `.tv-panel::after` gains core+spill radial layers in
  --accent seated on the step sockets — top at --pk4-td × 0.71
  (headerless) or --pk-hh + --pk4-tab × 0.45 (headered, the :has
  rule), bottom at 100% − --pk4-bd × 0.685 — over the standing
  --panel-glow bloom. All live; nothing baked.
- Side effect (intended): the auth panel's vector screw overlay
  (::after in steel.css) is replaced by these lights in Steel 4 —
  its corner bolts now come from the corner art itself.

## Metal-button wear (adjustment 4)

--btn-secondary-bg and --nav-item-bg/-hover (steel4 tokens) gain
btnwear.webp as their top layer; steel4.css sets
background-blend-mode: overlay on .tv-btn--secondary, .tv-icon-btn
and .tv-nav-item, restates .tv-tab with the same layer, and cuts a
brighter machined edge (inset highlights) into all four. Accent
plates (--btn-plate-art stack) untouched.

## Fallbacks / notes

- The popover menu keeps the previous steelworn kit via the --pk-*
  variables (small surface; documented min-size fallback). Table
  wrap keeps the family frame treatment.
- clip-path also clips the panels' outer drop shadow at the corner
  cuts (inset bevel + frame art carry the depth) — known tradeoff
  of a true clipped silhouette.
- PIL composites at 900×460 headered, 900×380 headerless,
  300×380 narrow, 190×260 tiny: corners, steps and light seats
  assemble cleanly at every size (verified visually).
