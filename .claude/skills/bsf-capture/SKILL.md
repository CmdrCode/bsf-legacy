---
name: bsf-capture
description: Record demo/promo video footage of Battleships Forever or ShipMaker running under wine — stage a scratch copy, drive it deterministically via the probe harness, capture with ffmpeg x11grab, encode deliverables. Use when asked to record, capture, film, or screenshot the game, make a demo/feature/promo video, or drive the game or ShipMaker with synthetic input.
---

# BSF capture & driving

An evolving runbook, earned by trial and error — trust it over first instincts.
**After every capture session, fold what you learned back in**: rules and
workflow here, details in [REFERENCE.md](REFERENCE.md).

Three path conventions used throughout. `scripts/…` is **this skill's own**
`scripts/` directory, not a repo-root one. Under `mods/…` the `*.gml` modules
are the repo's, but every lever and report file beside them (`probe.txt`,
`optreq`, `smres.txt`, …) is written and deleted at runtime inside the **staged
scratch game dir** — none of them exist in a clone, and `touch`ing one is how
you press a button. `_local/…` is the private side folder described in
`CLAUDE.md`, git-ignored and likewise not part of a clone — what is named there
is a local archive, never something to open.

## Hard rules (each one has ruined a take)

1. The game runs inside a **wine virtual desktop**. The WM only sees the outer
   window, titled `Default - Wine desktop` — focus with `wmctrl -a 'Wine desktop'`.
   Raising the inner game window does nothing, and its title changes with the
   current room, so never target it.
2. Synthetic mouse **clicks never reach the game** (in ShipMaker, wheel events
   don't either). Mouse *position* and *keyboard* do — after focusing the wine
   desktop. Press buttons via the probe-harness levers, never by clicking.
3. Refocus the wine desktop **before every synthetic keypress** — the user's
   terminal often sits above it. The user stays hands-off during a take.
4. **The grab rect is the rendered area, and it is measured, never assumed.**
   Two different things go wrong here and both hand back a plausible-looking
   frame of the wrong thing, which is why neither announces itself.

   *Which screen.* For x11grab offsets **trust xrandr, not wmctrl** — under
   fractional scaling wmctrl reports 2×-scaled coordinates. **Derive the offset
   every time**; the reference desktop has the 4K output at `+1080,0` and the
   next one measured had it at `+1080,1024`, so reusing that constant grabs a
   different monitor and hands back a screenshot of something else entirely.

   *Which part of the window.* The game does **not** fill its window.
   `mods/resolution.gml` sets `window_set_region_scale(-1, 0)` — fit keeping
   aspect — so a 1600×1120 region in a 3840×2160 wine desktop is drawn as
   **3086×2160 pillarboxed at +377,0**. Grab `region` at the window origin and
   you get a corner crop: no HUD, no minimap, and whatever sits past the crop
   line simply is not in the take. That happened here — a whole capture of the
   EP9 reveal in which the revealed ship fell outside the frame, and the ship
   left inside it was a *different* ship the reviewer read as the subject.
   Measure the rect from a frame instead, as the bounding box of everything
   that is not black:

       ffmpeg -f x11grab -video_size 3840x2160 -i :99.0 -frames:v 1 \
         -pix_fmt rgb24 -f rawvideo /tmp/r.raw
       # then: a = np.fromfile(...).reshape(2160,3840,3)
       #       np.nonzero(a.max(axis=(0,2)) > 8)[0]   -> 377 .. 3462
       #       np.nonzero(a.max(axis=(1,2)) > 8)[0]   -> 0 .. 2159

   `_local/captures/hestia-x-reveal-drive.sh` has this as a `measure_rect`
   function to lift. Round the result down to even dimensions — libx264 refuses
   odd ones. **Then confirm the take frames what you think it frames**: the HUD
   column and the minimap are at the region's right edge, so if they are missing
   the rect is wrong, whatever the footage looks like otherwise.
5. Never stage a capture in the canonical game dir — work on a scratch copy.
   **One game per staged copy**: `mods/edit/{cmd,ack,state}` is a fixed path
   inside it, so a second instance on the same copy fights the first for the
   channel *and* for the prefix's virtual desktop — commands stop being acked
   and the older instance stops rendering mid-take. Kill before relaunching,
   and confirm the count.
6. **Prove the display can be captured before you roll.** A locked session and a
   headless one both leave the game running, stepping and focusable, so every
   cheap signal says the take is fine while the footage is blank. One frame
   settles it — a grab of the root under ~5 KB is blank — and
   `loginctl show-session <id> -p LockedHint --value` names the locked case.
   Unlocking is the human's to do; your fix is to take it on Xvfb, which cannot
   be locked and does not touch their desktop. REFERENCE has the encoder
   signature (100% skipped P-frames) that identifies a take already lost.
7. **Never `pkill -f` / `pgrep -f` a pattern that appears in your own command.**
   A heredoc that merely *writes* the pattern counts, so the shell matches
   itself and `kill` takes out the caller (exit 144). It cost three shells in
   one session. Use `scripts/gamepids.py`, which walks `/proc` and excludes its
   own ancestry, or kill explicit PIDs captured at launch.
8. Launch the exe **directly** (`wine BattleshipsForever.exe`, cwd = the game
   dir). Routing through `wine explorer /desktop=…` breaks the load: no game
   window ever appears, `wine` still exits 0, and the take records an empty
   desktop for its whole length — so nothing reports the failure. Windowing
   already comes from the prefix's registry virtual desktop, so the flag buys
   nothing. `tools/game.py`'s `launch()` reaches the same conclusion from a
   *different* symptom (a stall at ~78 MB RSS that never finishes loading),
   which is reason to distrust any single causal story here and simply stay on
   the plain path.

## Workflow

1. **Stage**: copy the game dir to scratch; install the repo `mods/` plus
   `probe.on`, `res.cfg` (e.g. `3840` / `2160` lines), `mode.cfg` (`1`, as used
   for the 4K take).
2. **Launch** with `tools/game.py`'s env (shared wine prefix — see REFERENCE),
   cwd = the scratch game dir.
3. **Verify** `mods/probe.txt` is ticking (~3×/s) before driving anything.
4. **Drive** from a bash driver script: source
   [scripts/drive-lib.sh](scripts/drive-lib.sh) for `focus_game` / `glide` /
   `key` / `wait_probe` / `to_main_menu`; probe levers press buttons, arrow keys
   work pickers, mouse glides are cosmetic but do track in-game. That library is
   the reusable extract of the proven 4K-resolution driver — the complete
   drivers stay archived with their footage (step 7).
5. **Record** with x11grab, started from inside the driver script (capture
   command below), timed with sleeps around each beat. If captions are wanted,
   have the driver write a wall-clock marker log (see REFERENCE "Caption
   cards") — retrofitting timings onto an unmarked take means frame-archaeology.
6. **Captions** (optional): pause ~5.5 s on a freeze-frame popup card before
   each feature — `scripts/make-caption-card.py` renders the house card style,
   REFERENCE.md has the marker→freeze calibration and the one-encode ffmpeg
   assembly.
7. **Encode** the deliverables, then **archive** the driver script (plus
   marks.txt and card PNGs if captioned) next to the finished video in
   `_local/captures/`, and update this skill.

## Recording & encoding

Capture — cheap on CPU while the game runs, big file, cut later:

    ffmpeg -f x11grab -framerate 30 -video_size 3840x2160 -i :0.0+1080,0 \
      -c:v libx264 -preset ultrafast -crf 15 -pix_fmt yuv420p -t <secs> raw.mp4

Deliverables re-encoded from the raw file (captures are silent — x11grab has no
audio to budget for):

* **Master** (~archive quality): `-preset slow -crf 18`. The 4K take came out
  ≈ 72 MB for 33 s.
* **Share cut, ≤ 10 MB hard cap** — GitHub's README-attachment limit on the
  free plan, and comfortably Discord-able. **Try `-crf 18 -preset slow` first
  and check the size**: mostly-static editor footage compresses far below a
  computed bitrate (a 72 s 1080p ShipMaker demo landed at 8.3 MB, and a forced
  two-pass at the "required" bitrate came out bigger *and* worse). Only when
  crf overshoots the cap, target a bitrate:
  `kbps ≈ target_MB × 8000 / seconds × 0.95`, then two-pass
  `-b:v <kbps>k -preset slow`. (The 33 s 4K share cut landed at 9.4 MB.)

## Publishing

A repo-committed video never plays inline on GitHub. The ≤10 MB cut embeds in
the README only as a GitHub *attachment*: upload by dragging into a release
description in the browser **logged in as CmdrCode** (never the web README
editor — that commits as web-flow and breaks the identity pins), then paste the
generated `user-attachments` URL on its own line in README.md and commit
locally as usual.

## Deeper knowledge

[REFERENCE.md](REFERENCE.md) — probe/lever inventory, geometry and coordinate
math, launch recipe, ShipMaker driving (drag levers, focus-freeze wake), plain
prefix vs virtual desktop, GNOME/mutter fullscreen quirks.
