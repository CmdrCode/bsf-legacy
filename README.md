# Battleships Forever — Legacy

I loved playing *Battleships Forever* (Sean "th15" Chan, Wyrdysm Games, 2007) when I was
younger, and always wished there was a sequel — or that it got improved. BSF-Legacy is a mod
I built so that new players can discover BSF with a modern visual feature set and no OS
compatibility issues: real widescreen, real resolutions, crisp text, and a serious speedup if
you play under wine. From here I'm hoping to extend the campaign, add more generic mod
support, and multiplayer.

It ships no part of the game. You bring your own copy — **this only works with v0.90d** —
the patcher edits it in place, and everything can be switched back off. The original
download links are long gone; [this Internet Archive capture](https://web.archive.org/web/20140322015221/http://www.wyrdysm.com/battleshipsforever/battleshipsforeverv090d.zip)
seems to be the last copy of v0.90d still online.

https://github.com/user-attachments/assets/36530b08-6ba3-4629-95e8-358479b19e0f

## How it works

The patcher makes one small edit to the game's startup code: a bootstrap that runs
`mods/init.gml` if it exists. That file chains the rest — every module is a plain GML text
file, compiled at load by the game's own engine, so it sees every game object, sprite and
room by name exactly as the game's own code does.

From there the modules build new objects and rooms, and rewire the stock ones at the event
level: GML can't edit existing code in place, but it can append to an event or replace one
outright, which turns out to be enough for everything here. Editing a mod is editing a text
file; no repatch, no tools.

Only two changes go deeper: the HWVP fix is a two-byte patch to the executable, and the
cursor cache is a native DLL that hooks a Windows API import.

## What it changes

**The game**

* True widescreen support. Any aspect ratio without stretching; the camera, zoom and main
  menu all adapt. (Stock "Widescreen" was 1280×960 — that's 4:3.)
* High-resolution support. An in-game resolution picker for any mode your monitor supports,
  applied live and rendered natively rather than upscaled, plus a fullscreen/windowed toggle.
* Fullscreen is a borderless fullscreen window, not a display mode change. Stock BSF changes
  the desktop resolution; this leaves it alone, so alt-tab is instant and nothing rearranges
  your other windows.
* A rebuilt options screen with every setting in one place. Stock has two options screens and
  neither is complete.
* Crisp menu text. Labels are drawn from the game's own font instead of magnified
  1024×768 bitmaps.
* No more "Error defining an external function" dialogs on every launch.
* Off-screen sections, turrets and doodads skip their draw — worth a few ms in big battles.

**The Ship Maker**

* Renders 1:1 at any window size instead of stretching a fixed 1016×704 canvas.
* Middle-mouse drag pan (stock teleports the canvas to the click point), with a live zoom % readout.
* A Factorio-style part picker: a paged quickbar, a hand that keeps placing, `Q` pipette, and an `E` searchable inventory of every part.
* Fixed mouse-cursor issues that broke part-dragging under Linux/wine.

https://github.com/user-attachments/assets/72e70ac7-94cd-4c5a-8998-53b53cf1a9a7

**Faster under wine** — BSF is far slower under wine than it should be, for reasons that are
wine's, not the game's. These help both the game and the editor:

* HWVP — two bytes in the exe flip Direct3D 8 from software to hardware vertex processing.
  15 → 27 fps under wine, near-nothing on Windows, and provably no visual change.
* Cursor cache — hooks the `GetCursorPos` import and serves ~160 reads a frame from a cache.
  `mouse_x` costs 176 µs a read under wine; this buys ~13 ms a frame. Cheap on Windows, so
  the Windows installer leaves it out.

## Install

**Windows:** grab `BSF-Legacy-Installer.exe` from the Releases page, drop it in your
Battleships Forever folder, run it. It checks it has the right game before touching anything,
and it is safe to re-run to update. Note an update restores any `mods/*.on` markers you
deleted.

**From source (any OS):** Python 3, no third-party dependencies.

```bash
cp -r mods /path/to/BattleshipsForever/
python3 tools/patch_bsf.py /path/to/BattleshipsForever/BattleshipsForever.exe
python3 tools/patch_bsf.py /path/to/BattleshipsForever/ShipMaker.exe   # the editor too
```

The Windows installer patches both automatically when `ShipMaker.exe` is present.

On Linux the patcher also drops `BattleshipsForever_Linux.sh` and `ShipMaker_Linux.sh`
next to the exes — from then on those are how you play: each runs its exe under wine
in a private prefix (`~/.local/share/bsf-legacy`), created automatically on the first
run in about ten seconds. No winetricks, no wine configuration, nothing outside that
folder; wine itself comes from your distro (`sudo apt install wine` or equivalent),
and the script tells you exactly what to install if it is missing. `--revert`
removes the launcher again.

The cursor cache additionally needs `bsfnat.dll`, cross-compiled with mingw-w64 via
`tools/build.sh`; skip it with `--no-cursor` and everything else still works.

## Turning things off

| what | how to disable |
|---|---|
| `crisp.gml`, `logo.gml`, `legacy.gml`, `cursor.gml` | delete the matching `mods/*.on` marker |
| `fastdraw.gml` (the draw cull) | create `mods/fastdraw.off` — it is opt-*out* |
| `smres.gml` (ShipMaker 1:1 resolution) | create `mods/smres.off` — it is opt-*out* |
| `smpan.gml` (ShipMaker middle-mouse drag pan) | create `mods/smpan.off` — it is opt-*out* |
| `smzoom.gml` (ShipMaker zoom % readout) | create `mods/smzoom.off` — it is opt-*out* |
| `smpick.gml` (ShipMaker part picker) | create `mods/smpick.off` — it is opt-*out* |
| `resolution.gml`, `options.gml`, `aspect.gml`, `widescreen.gml` | rename or delete the `.gml` itself |
| the HWVP bytes | `--revert-hwvp` |
| the mod loader + error-dialog flag | `--revert` (restores the `.bak`) |

No repatch needed for the module-level ones, so this is also how you A/B things yourself.

## What the patcher writes to the exe

It knows both v0.90d executables — the game and `ShipMaker.exe` — and refuses anything it
does not recognise (the build is hashed with the HWVP bytes normalised out, so a
half-patched copy still matches):

* **the mod loader** — a one-line bootstrap space-padded over a dead comment in the resource
  tree (the game's runs `mods/init.gml`, ShipMaker's runs `mods/sm.gml`), same length in and
  out, so nothing else moves;
* **HWVP** — the two device-flag bytes, patched by verified file offset, never by pattern;
* **the error-display flag** — one `1` → `0` in the settings block (game only; ShipMaker
  has no spurious startup errors to silence);
* **ShipMaker only:** ten hardcoded `window/1016`-style menu-positioning expressions,
  rewritten same-length for the 1:1 region model.

The cursor cache writes no bytes at all — it is a DLL plus two files in `mods/`. Everything
under `mods/` is plain GML text executed at runtime.

```bash
python3 tools/patch_bsf.py <exe> --revert          # restore the .bak
python3 tools/patch_bsf.py <exe> --revert-hwvp     # undo just the two bytes
python3 tools/patch_bsf.py <exe> --revert-cursor   # remove the cursor cache
python3 tools/patch_bsf.py <exe> --hwvp-only       # just the two bytes, no mod loader
```

## Credit

Battleships Forever is the work of **Sean "th15" Chan** and Wyrdysm Games. The game is
freeware, but its code, art and ship designs remain his. Nothing in this repository is
derived from or redistributes any of it — a fresh clone works as-is, with no extraction
step.

## Licence

MIT, covering the original work in this repository only — see `LICENSE`. It grants no rights
over Battleships Forever itself.
