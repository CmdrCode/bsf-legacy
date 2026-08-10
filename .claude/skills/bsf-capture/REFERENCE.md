# BSF capture & driving — reference

Facts measured on the reference desktop (GNOME on X11, fractional scaling, three
monitors, 4K on DP-2). Dated notes mark when a fact was established; re-verify
anything old if the desktop setup changes, and treat every geometry number here
as belonging to that setup rather than to the tools.

## Windows, focus, and the wine virtual desktop

* The game normally runs inside a wine **virtual desktop** (set in the prefix
  registry). The X/WM level sees only the outer window `Default - Wine desktop`;
  `wmctrl -a 'Wine desktop'` raises and focuses it.
* The inner game window is invisible to the WM for stacking purposes, and its
  title follows the room caption (`Options` on the options screen) — useless as
  a stable target.
* ShipMaker **freezes when the wine desktop loses focus**, and `wmctrl -a`
  alone does not wake it — send a real input event (an `xdotool click` into the
  window works as a wake-up even though clicks never reach the game's input
  queue). Confirm it is stepping again by watching `mods/smres.txt` tick.

## Input: what reaches the game

| synthetic input        | game | ShipMaker |
|------------------------|------|-----------|
| keyboard (after focus) | yes  | yes (F12 = hide-GUI toggle confirmed) |
| mouse position         | yes  | yes |
| mouse clicks           | no   | no (but a click still *wakes* a frozen SM) |
| mouse wheel            | —    | no — SM zoom is wheel-only (obj_sidebar events 60/61), so zoom cannot be driven |

Input rules are also documented at the bottom of `mods/options.gml`.

## The probe harness (game)

Enabled by `mods/probe.on`; harness lives in `mods/init.gml`.

| file           | direction | effect |
|----------------|-----------|--------|
| `mods/probe.txt` | out     | room / window / mouse state, written ~3×/s |
| `mods/optreq`  | in (touch) | presses the real main-menu Options button (`GUI_MainOptions`' own action) |
| `mods/uiev`    | in        | fires options-screen user events |
| `mods/goto.txt`| in        | jumps rooms |

Main menu is `room=1` in `probe.txt`; recover to it by sending Escape and
re-checking (see `to_main_menu` in scripts/drive-lib.sh).

## ShipMaker driving

* **Prefer a fresh plain prefix (native WM window) for driving SM** — tested
  2026-08-08: no focus-freeze at all, mouse-position levers work with the
  window unfocused, glides land while the user keeps typing elsewhere. The
  shared prefix used for the game has a virtual desktop in its registry, so
  plain `wine ShipMaker.exe` there opens INSIDE a "Default - Wine desktop"
  window, not native — use `WINEPREFIX=<scratch>/prefix` (fresh, ~7 s create)
  to actually get a native window.
* Under a virtual desktop the freeze is worse than "lost focus": it RE-ARMS
  the moment the pointer enters the SM window while the desktop is unfocused,
  and a wake click on the inner SM window does not reliably revive it — click
  the desktop's blue background instead, then act fast; any focus flick back
  to the user's terminal freezes it again mid-glide.
* Same wine env as the game; launch `wine ShipMaker.exe` with cwd = the
  game dir.
* Pan lever pattern (used to verify mods/smpan.gml): in the scratch copy only,
  reroute smpan's press/release tests to `file_exists("mods/panon")`, then
  touch panon → glide → rm panon, and read `view1=` from smres.txt. A +200,+100
  px glide moved view1 by exactly −200,−100 at zoom 1.
* Deterministic control comes from `mods/smres.gml` itself:
  * `mods/smsize.txt` (`W\nH`) → resizes the window;
  * `mods/smres.txt` → state report on every apply, and every 60 steps when
    `mods/probe.on` exists.
* **Drag levers** (temporary levers in smres.gml, built for the drag-fix
  measurements): `mods/dragreq` starts a core group-move exactly like the stock
  path (dragged/setGroupMove/object_dragged + warp + mxprevious reset);
  `mods/dropreq` releases. Stream motion as repeated small
  `xdotool mousemove_relative` chunks (~3 px, several per frame) — one big
  burst lands in a single game frame and proves nothing.
* SM applies `mxchange` once per visible view — 2× with GUI shown, 1× under
  F12 hide-GUI (stock behaviour). Compare delta sums, not core distance.
* Pristine exe lives in the original v0.90d distribution zip
  (`battleshipsforeverv090d/ShipMaker.exe`, sha256 3d5932fb…). The canonical
  dir's copy is already HWVP-patched — compare hashes with
  `patch_bsf.sha256_build` (HWVP-normalised), never raw sha256.

## Geometry

* xrandr: 4K monitor DP-2 at offset `+1080,0` →
  `ffmpeg -f x11grab -video_size 3840x2160 -i :0.0+1080,0`.
* wmctrl reports **2×-scaled** coordinates under fractional scaling — never use
  them for grab offsets or mousemove targets; trust xrandr.
* To grab a native window (e.g. ShipMaker in a plain prefix) use
  **`xwininfo -id $WID`'s "Absolute upper-left X/Y"** for the client area.
  `xdotool getwindowgeometry` is frame-offset (measured +14,+49 on the
  reference desktop) — grabbing from it clips the top of the window and captures a strip
  of whatever sits below/right of it (2026-08-08).
* World→screen mapping at 4K: **×2.8125** (game view 1365×768 → 3840×2160),
  then add the +1080 monitor offset to X.

## Launch recipe

1. Copy the game dir to a scratch location (never capture in the canonical dir).
2. Install the repo `mods/` + `probe.on` + `res.cfg` (`3840` / `2160`) +
   `mode.cfg` (`1`).
3. Launch with `tools/game.py`'s env, which resolves the shared wine prefix.
4. Wait for `mods/probe.txt` to tick before driving.

## Plain prefix (no virtual desktop) — tested 2026-08-07

* A fresh win32 prefix takes ~7 s to create; `WINEDLLOVERRIDES="mscoree,mshtml="`
  keeps it silent.
* SM as a native WM window: resize-by-frame drives the 1:1 region, no
  focus-freeze wake dance, levers work.
* mutter **ignores mid-session `window_set_size`** (boot-time restore works;
  SM's own 1016×704 snap-back is equally ignored — symmetric).
* Game fullscreen on the reference desktop: mutter parks the borderless window at y=32
  (top bar) and never grants `_NET_WM_STATE_FULLSCREEN`, not even via
  `wmctrl -b add,fullscreen`. Escape hatch:
  `AppDefaults\BattleshipsForever.exe\X11 Driver` → `Managed=N` covers the
  whole monitor but is kiosk mode (WM can't raise anything above it).
* Verdict: the wine **virtual desktop stays the robust fullscreen path** on this
  desktop; options.gml's fullscreen is a borderless screen-sized window +
  drift watchdog (never GM fullscreen — it ignores `window_set_size`).

## Modeset-on-exit blackout — fixed 2026-08-08

* Symptom: closing the game/editor blanks **all monitors** for a few seconds.
  Cause: a *clean* exit tears the D3D device down and wine re-enumerates the
  displays (`xrandr:get_gpu_properties_from_vulkan` for each GPU in the trace),
  which on a multi-monitor NVIDIA setup triggers a full modeset.
* Proven by counting root RandR events during exit
  (`xev -root -event randr | grep -c Notify`): a clean `game_end()` fired **30**,
  a hard `wineserver -k` (skips the teardown) fired **0** — which is what pins
  it to the shutdown path, not startup. To drive a clean exit synthetically
  (clicks don't reach the EXIT button), add a temp lever to the scratch
  `smres.gml` Step: `if (file_exists("mods/quitreq")) { file_delete(...); game_end(); }`.
* Fix, baked into the launcher's private prefix (`patch_bsf.py`):
  `wine reg add "HKCU\Software\Wine\X11 Driver" /v UseXRandR /d N /f`. Drops the
  30 events to 0. Safe because the mods render in a borderless window and never
  change the display mode — and `display_get_width()` still returns the primary
  (3840), so the game still opens full-width on the right monitor.
* Launcher applies it once behind a `$WINEPREFIX/.bsf-no-xrandr` marker, so an
  existing prefix picks up the fix on its next launch with no repatch.

## Caption cards — freeze-frame feature captions (2026-08-08)

The part-picker demo (`_local/captures/shipmaker-part-picker-demo.mp4`) pauses
5.5 s on a styled popup card before demonstrating each feature. The pipeline,
all reusable:

* **Cards**: `scripts/make-caption-card.py OUT.png TITLE [--key E] --line …`
  renders a full-frame transparent PNG in the house style — near-black panel
  `(6,12,6,238)`, 2 px `(0,170,0)` border + `(0,70,0)` inner hairline, radius
  10, blurred drop shadow; title in the game's Visitor font
  (`_local/mockups/visitor1.ttf`, 40 px, `(140,255,140)`) with an optional
  keycap chip; body DejaVu Sans 27 px `(208,216,208)`; panel centered on x at
  y≈400, which clears both the bottom quickbar and center-canvas action.
  **Reuse this script and its tokens for future videos — don't restyle.**
* **Marker log in the driver**: `mark(){ echo "$(date +%s.%N) $1" >> marks.txt; }`
  called right before ffmpeg launch (`fflaunch`), at every card boundary, and
  right before one visually unambiguous event for calibration. Follow each
  card mark with `sleep 1.0` of deliberate stillness so the freeze can land
  anywhere within ±0.4 s of the intended point.
* **Wall→video calibration**: detect the calibration event in the footage and
  solve the offset. Modal-open scans reliably: >300 green-outline pixels
  (`g>90, r<0.8g, b<0.8g`) in the search-box strip rows 55–90, cols 700–1385
  of the 1920×1080 client. Offset measured ≈0.06 s (x11grab starts nearly
  instantly), but measure per take, don't assume.
* **Freeze points**: `t_video(cardN) = t_wall_rel(cardN) − offset + 0.5`
  (mid-stillness).
* **Assembly in ONE ffmpeg filter_complex** so every piece shares one encode
  (concat of separately-encoded files invites param mismatches): freeze =
  `trim=start=T:end=T+0.04,setpts=PTS-STARTPTS,loop=loop=<fps×hold−1>:size=1:start=0,setpts=N/(30*TB)`
  then `overlay` the card (image input given `-framerate 30 -loop 1 -t <hold>`,
  overlay with `shortest=1`); gameplay segments plain `trim,setpts=PTS-STARTPTS`;
  chain into `concat=n=…:v=1:a=0,format=yuv420p`, encode `-crf 18 -preset slow -r 30`.
* **Hold length**: 5.5 s per card (user-calibrated reading pace — 3.4 s felt
  rushed for two-line bodies).
* **Review in Chrome**: plain `python3 -m http.server` cannot serve video
  (Chrome requires Range/206); use `scripts/serve_range.py PORT DIR`.

## Archive convention

Every finished video lands in `_local/captures/` with its driver script beside
it (e.g. `drive-capture.sh` next to `bsf-legacy-4k-menu-resolution.mp4`), so a
take can be reproduced or restaged later. Captioned takes also archive their
`marks.txt` and card PNGs (e.g. `smpick-demo-assets/`). `_local/` is
git-ignored and hook-blocked — captures and scripts never publish.
