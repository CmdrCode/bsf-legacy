# BSF capture & driving — reference

Facts measured on the reference desktop (GNOME on X11, fractional scaling, three
monitors, 4K on DP-2). Dated notes mark when a fact was established; re-verify
anything old if the desktop setup changes, and treat every geometry number here
as belonging to that setup rather than to the tools.

Paths follow [SKILL.md](SKILL.md)'s convention: `scripts/…` is this skill's own
`scripts/` directory, and `_local/…` is the git-ignored private folder — named
here to record where a take was archived, never as something a clone can open.

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

## Where is the game actually drawing? — 2026-08-22

The window is not the picture. `mods/resolution.gml` calls
`window_set_region_scale(-1, 0)` — fit-to-window keeping aspect — so the render
region is scaled up until one axis fills the window and the other is
letterboxed. Measured on a 3840×2160 wine virtual desktop with
`region=1600x1120`: the picture is **3086×2160 at +377,0**, and `xwininfo`
reports the game window as 3840×2160+0+0, which is true and useless.

Three numbers, and only one of them is the grab rect:

| what | where it comes from | value in that run |
|---|---|---|
| window | `xwininfo`, and `win=` in `mods/edit/state` | 3840×2160 at +0,0 |
| region | `window_get_region_width()`, `region=` in `state` | 1600×1120 |
| **picture** | measured from a frame | **3086×2160 at +377,0** |

Derive it if you like — `h_pic = win_h`, `w_pic = win_h × region_w / region_h`,
centred — but **measure it anyway**, because the derivation assumes the fit axis
and the centring, and a frame settles both for the cost of one grab. The
bounding box of everything that is not black is the rect; `measure_rect` in
`_local/captures/hestia-x-reveal-drive.sh` is the copy to lift. Round down to
even dimensions or libx264 refuses the encode.

**How this fails is the point.** Grabbing `region` at `+0,0` — the obvious
wrong guess, since both numbers are real and sit next to each other in `state`
— produces a corner crop of an upscaled frame. It is in focus, correctly
exposed, full of game, and framed almost sensibly, so nothing in the file says
it is wrong. It cost a complete take of the EP9 Hestia X reveal: the ship that
decloaks landed just past the crop line, a *different* Hestia sat inside it, and
the take was handed over as showing the reveal. The cheap check is the HUD —
the green column and the minimap live at the region's right edge, so **a frame
with no HUD column is a cropped frame**, whatever else it looks like.

World→screen, once the rect is right, comes from the dump header
(`viewx viewy vieww viewh`) and the region:

    logical_x = (world_x - viewx) × region_w / vieww
    picture_x = logical_x × pic_w / region_w        # + the rect offset for the root

## Driving a mission headless without it ending under you — 2026-08-22

A seek does not leave the mission in a state that survives being left alone.
Two separate things end the run early, and both look like the game hanging: the
process is alive, `mods/probe.txt` stops ticking, commands go unacked, and there
is no error anywhere.

* **The player dies.** `seek` restores world state and drops the player wherever
  the beat left her, with nobody flying. In EP9 that is inside the meteor storm.
  MISSION FAILED comes up, the room stops stepping, and the take is of a mission
  that ended seconds in. **`edit 1` before the seek** — the editor's rules
  disable storm damage and `missionFail`. Cheap tell: `ships=` in
  `mods/edit/state` drops by one.
* **The ladder walks on without you.** `GUI_Messager` destroys itself on a timer
  (`l_counter > string_length(l_text) × GUI_MessageReadTimeMul + GUI_MessageReadTime`,
  counted in the Draw event), *not* on input — so a headless run with nobody
  pressing anything still advances through every remaining beat and reaches the
  end screen. Park the counter on a value with no branch and clear the pause
  alarm:

      with (global.a2m1_ctr) { l_messagecount = 900; alarm[3] = -1; }
      with (GUI_Messager) instance_destroy();

  Then fire each beat by hand and the scene holds still for as long as needed.

Check the whole root, not the game rect, when a run looks stuck — the earlier
diagnosis here was wrong twice for the same reason. A cropped screenshot showed
`MISSIO…` and was read as MISSION ACCOMPLISHED; the full root said **MISSION
FAILED — YOUR SHIP WAS DESTROYED**, which is a different bug with a different
fix.

**`global.ed_res` cannot carry a value back.** The editor overwrites it with its
own ack (`handed to execute_string`) after `execute_string` returns, so a probe
that sets it reads back the ack every time. Have the probe write its own file
under `mods/edit/` and read that.

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
* Verdict: the wine **virtual desktop stays the robust fullscreen path** on the
  reference desktop; options.gml's fullscreen is a borderless screen-sized
  window + drift watchdog (never GM fullscreen — it ignores `window_set_size`).

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

The part-picker demo (archived as `shipmaker-part-picker-demo.mp4`) pauses
5.5 s on a styled popup card before demonstrating each feature. The pipeline,
all reusable:

* **Cards**: `scripts/make-caption-card.py OUT.png TITLE [--key E] --line …`
  renders a full-frame transparent PNG in the house style — near-black panel
  `(6,12,6,238)`, 2 px `(0,170,0)` border + `(0,70,0)` inner hairline, radius
  10, blurred drop shadow; title in the game's Visitor font (40 px,
  `(140,255,140)`) with an optional keycap chip — that face ships with the game
  rather than with this repo, so point `$BSF_VISITOR_TTF` at it; body DejaVu
  Sans 27 px `(208,216,208)`; panel centered on x at y≈400, which clears both
  the bottom quickbar and center-canvas action.
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

## Staging traps — 2026-08-22

Found while verifying a new mod headlessly rather than capturing.

* **Clear `mods/` in the staged copy, and install the DLLs from the repo build.**
  A `cp -a` of the game dir brings across whatever the last session left there —
  including a `bsfshader.dll` that is a *different build* from the one
  `tools/build.sh` produces now (same size, different hash, measured). A stale
  DLL changes `external_define` behaviour and the run then measures the wrong
  binary under the new name. Same class as the "fail loudly if the variant exe
  is missing" rule below.
* **`tools/game.py --help` is not a help flag.** `game.py` treats its argument as
  a command, so that invocation attempts a *launch* against the canonical
  install on the inherited `DISPLAY`. Read the file for the verbs rather than
  probing for them.
* **A verification run wants no capture at all.** For "does this mod load, and
  what does it throw", the whole loop is: stage → `probe.on` → launch on Xvfb →
  read `mods/probe.txt`, the module's own breadcrumb, and `game_errors.log`.
  Count error *blocks* against a baseline run with the module gated off — an
  absolute count means nothing, because BSF's own BASS audio defines fail ~40
  times on any box with no sound device.
* **Give a new module a breadcrumb file.** `execute_file` on a file that will not
  compile does nothing, silently, so "no breadcrumb" and "breadcrumb says
  `start` but not `ok`" are the two diagnoses you otherwise cannot tell apart.
  `battle.gml` and `cloak.gml` both do this.

## The cloak rig is a ready-made instrument — 2026-08-22

`mods/cloak.gml`'s regression rig answers "did I break the cloak" in about
forty seconds, and it is the fastest way to test any change to that file *or* to
the mission-facing variables it exposes. Stage, then drop three files in
`mods/`: `cloak_demo.on`, `battle.on`, and a one-ship `battle.cfg` —

    2048 / 2048 / 60 / 12345 / 1 / 1 / Hecate / 1 / 1024 / 1024 / 0 / 0

(one value per line: room w, h, menu step to enter on, seed, nwaves, then the
wave's step, object, count, cx, cy, spread, period). Any stock hull works — the
rig creates the UmbraCloak mount itself and points `l_owner` at the first
`ctr_Ship` on the field, so nothing custom has to be in the room. It calls
`game_end()` at rtick 310, so the run ends itself; no driver and no capture.

What each output proves, in the order worth reading them:

* `mods/cloak.log` — `ok …` means the file compiled all the way through. `start`
  alone means it died partway, and no file means it never ran. This is the whole
  reason the breadcrumb exists; read it first.
* `mods/cloak_trace.txt` — **the real instrument**: one line per tick from 145 to
  300 with `now`, `hidden`, `want`, `bud`, `slot`, `parts`, `depth`. A healthy
  transition steps `now` by exactly 1/60 per tick, flips `hidden` at the start,
  holds `parts` non-zero throughout, and returns `slot` to -1 with `depth` back
  to its own the tick it settles. `parts=0` during a transition is the signature
  of a part scan that was skipped — the scan only runs while `now >= 1`.
* `mods/cloak.txt` — `hull_append=1` is the one that matters most (the appended
  `ctr_Ship` Create really ran), plus `binds`/`fails` for the shader.
* `game_errors.log` — count *blocks* (`grep -c 'ERROR in'`). ~40 of them are BSF's
  own BASS defines failing on a box with no sound device, and one more
  `ctr_PartDrawer` block on **Game End** is the rig's own `game_end()` unwinding.
  Neither is a finding.

**The rig writes 36 full-screen PNGs.** At the 4K virtual desktop that is 33 MB
each — **1.3 GB** in the staged copy. Copy out `cloak_trace.txt` and delete the
scratch dir, or stage at a smaller `res.cfg` if the frames are not the point.

`cloak.txt` and the last frames land a few seconds after the trace stops; a read
timed off the trace alone reports them absent when they are merely late.

**The rig proves the module; it does not prove the mission.** For a mission-side
reveal, sample the hull directly instead — pin the ladder (see "Driving a
mission headless…"), fire the spawn, and append `l_cloak_now` to a file every
few hundred ms. The EP9 Hestia X reads
`now=0.08 → 0.30 → 0.50 → 0.70 → 0.92` with `want=0 lock=1 snap=-1` throughout,
which is the whole contract in one line of output: `snap` spent, `lock` held by
the mission, `want=0` meaning *cloak off* — so the target is **solid**, not
invisible. That last one is worth saying out loud, because `l_cloak_want = 0`
reads like "wants to be invisible" and is the opposite:
`eng = l_cloak_want; tgt = 1; if (eng == 1) tgt = 0;`.

Five samples over two seconds cost nothing and settle "is the reveal broken" on
their own — **before** any question about whether the *capture* showed it. Do
them in that order; the reverse wasted a session here.

## Two more staging traps — 2026-08-22

Both cost a run each while verifying a compiler change headlessly.

* **Size the Xvfb screen to the prefix's virtual desktop, or the game does not
  start at all.** The note above says to match it; the failure when you do not
  is worth knowing by sight, because nothing in the game's own logs mentions it:

      X Error of failed request:  BadWindow (invalid Window parameter)
        Major opcode of failed request:  1 (X_CreateWindow)

  wine exits, no module ever loads, and every breadcrumb file is simply absent —
  which reads exactly like "my mod failed to compile". A 1280x1024 screen under
  a 3840x2160 `Default` desktop is enough to trigger it.
* **`cp -a` of the game dir brings the canonical install's `game_errors.log`
  across**, timestamps and all. Counting blocks in it then measures whatever the
  last real session did — a 4.6 MB log from another day. `rm` it as part of
  staging, next to clearing `mods/`.

## Timing anything against a GM7 alarm

GM7's per-step order is **Begin Step -> Alarm -> Step**, so a tick counter
incremented in Step reads one *low* when an alarm event samples it. Measuring
`alarm[n] = 75` that way reported a 74-step delay and looked like an off-by-one
in the code under test; moving the counter to Begin Step reported 75, which is
the truth. Put the counter in Begin Step before concluding anything about alarm
latency.

## Can this display be captured at all? — 2026-08-22

**Check before every take, not after.** A locked session and a headless one both
leave the game running and stepping normally, so every signal you would
instinctively trust says the take is fine: the process is alive, `mods/edit/state`
ticks, `wmctrl -a 'Wine desktop'` reports success, ffmpeg exits 0. The footage is
blank. One take was lost to this and diagnosed only from the encoder stats.

**The tell is in the encode, and it is unmistakable:**

    frame P:597  Avg QP: 5.01  size: 16
    mb P  ... skip:100.0%

100% skipped P-frames means nothing moved for the whole take. A 20-second 4K
capture that lands at **88 KB** is the same fact in one number. Do not go looking
for a mod bug; go looking for a display.

**The three states, and how to tell them apart:**

    loginctl show-session $(loginctl list-sessions --no-legend | awk 'NR==1{print $1}') \
        -p Type -p Active -p LockedHint --value

* `LockedHint=yes` — **locked**. The game runs behind the lock screen and
  x11grab reads the *whole root* as blank, not just the game window. Nothing you
  can do from a shell fixes this and nothing should: unlocking is the human's.
  `xset dpms force on` does not help, and `xset q` will cheerfully report
  `Monitor is On` throughout, so it is not the check you want.
* No session on that display — **headless**. Fine, and preferable; see below.
* `Active=yes`, `LockedHint=no` — capturable.

**One-line pre-flight**, cheaper than any of the above and it catches all cases,
because it asks the only question that matters:

    ffmpeg -f x11grab -video_size <root> -i $DISPLAY -frames:v 1 -y /tmp/probe.png
    # a PNG under ~5 KB is a blank root: do not start the take

**What to do instead: take it headlessly.** Xvfb does not care whether anyone is
logged in, cannot be locked, and does not touch the human's desktop — so it is
the *default* for an unattended take, not the fallback. `Xvfb :99 -screen 0
3840x2160x24`, sized to the prefix's virtual desktop (the "Headless
boot/splash capture" section below has the rest, and the BadWindow signature if
you get the size wrong). Grab `:99.0` with **no offset**: the desktop maps 1:1,
which also sidesteps the multi-monitor offset arithmetic entirely.

**If you must use the real display**, derive the offset, never reuse one. Hard
rule 4 says trust xrandr, and this is why: the reference setup has the 4K output
at `+1080,0`, and the desk it was re-measured on had it at **`+1080,1024`**.
Grabbing the remembered constant captured a different monitor and returned a
screenshot of an unrelated window that looked plausible enough to reason from.

    GEO=$(xrandr --listmonitors | awk '/DP-2/ {print $3}')   # 3840/941x2160/529+1080+1024
    SIZE=$(echo "$GEO" | sed -E 's#([0-9]+)/[0-9]+x([0-9]+)/[0-9]+.*#\1x\2#')
    OFF=$( echo "$GEO" | sed -E 's#.*[0-9]+\+([0-9]+)\+([0-9]+)$#\1,\2#')

## Serving a capture to look at it — 2026-08-22

`scripts/serve_range.py PORT DIR [HOST]`. Range support is the point: Chrome
needs `206 Partial Content` or the video will not scrub, and a plain
`python3 -m http.server` gives it `200` and a seek bar that does nothing.

HOST defaults to loopback; `tailscale` resolves this node's tailnet address and
binds **that one address**, so the LAN gets nothing. Verify rather than assume —
`ss -ltn | grep <port>` must show the tailnet address and not `0.0.0.0`:

    python3 scripts/serve_range.py 8736 _local/captures tailscale
    curl -o /dev/null -D - -H 'Range: bytes=0-1023' http://<tailnet-ip>:8736/x.mp4

There is no authentication of any kind, and `_local/` is the folder that is
private by design, so bind the narrowest address that reaches the device you
want to watch on. Pick a port and check it first: 8735 was already held.

## Archive convention

Every finished video lands in `_local/captures/` with its driver script beside
it (e.g. `drive-capture.sh` next to `bsf-legacy-4k-menu-resolution.mp4`), so a
take can be reproduced or restaged later. Captioned takes also archive their
`marks.txt` and card PNGs (e.g. `smpick-demo-assets/`). `_local/` is
git-ignored and hook-blocked — captures and scripts never publish.

## Headless boot/splash capture under Xvfb — 2026-08-21

Proven while measuring the loading bar (engine notes §26–27). For watching the
runner's own boot phase — splash, load bar, "does this exe boot at all" — no WM
and no real display are needed.

* `Xvfb :99 -screen 0 3840x2160x24`, sized to the prefix's `Default` virtual
  desktop so the desktop maps 1:1. The splash (550 wide, and 168 tall since
  the bar landed) centres on it, so an
  `ffmpeg -f x11grab -video_size 1280x720 -i :99.0+1280,720` region grab
  catches it with room to spare at a tenth of the pixels.
* Launch directly with the usual `game.py` env plus `DISPLAY=:99`, cwd = the
  staged dir (hard rule 8 — `wine explorer /desktop=…` is how a whole run of
  splash measurements came back void).
* 10 fps PNG frames are plenty; the splash lives ~8 s. Verdict signatures: a
  healthy boot shows the splash within ~1 s and the game window ~8 s later; a
  desynced gamedata stream shows **no window at all for 45 s** and the loader
  exits silently — `display_errors` never gets a say.
* Tear down by PID, never by name: keep the Xvfb pid in a file, and free a
  squatted display with `fuser -k /tmp/.X11-unix/X99`. A `pkill -f` whose
  pattern appears anywhere in the calling command text (a heredoc that writes
  the script counts) kills the caller — same trap `tools/game.py` documents
  for the exe name, and it cost two diagnostic runs before it was recognised.
* When cycling variant exes through one staged copy, make the runner **fail
  loudly if the variant is missing** — a silent `cp` failure re-measures the
  previous exe and hands back its results under the new name.
