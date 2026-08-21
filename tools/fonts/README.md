# Visitor TT1 / TT2 BRK

The two faces Battleships Forever sets its own interface in. They are **build-time
only**: `tools/splash.py plate` uses them to draw `tools/splash-plate.png`, and it
is the plate that ships. Patching a game needs neither these files nor any other
font.

They are checked in rather than looked for because nothing else can supply them.
GM 7.0 font resources store a face **name and size, not glyphs** (`MainMenuFont`
-> "Visitor TT1 BRK", size 42), so the runner asks Windows for them at load time
and no font ships in the v0.90d package -- which is also why the game's own menus
render in a substitute on a machine that has not got them.

| file | family | version | used for |
|---|---|---|---|
| `visitor1.ttf` | Visitor TT1 BRK | 3.11 | `MainMenuFont`, `TextFontLarge` — the wordmark |
| `visitor2.ttf` | Visitor TT2 BRK | 3.22 | `TextFont` — smaller interface text |

Both are by Brian Kent (Ænigma Fonts) and are freeware, redistributed unmodified
and byte-for-byte as published. Their embedded copyright string carries the
foundry's own credit and contact address; that is the author's attribution and
stays as it is. The originals come from dafont:

    curl -sL 'https://dl.dafont.com/dl/?f=visitor' -o visitor.zip

The version line is set in a mono, which is **not** bundled -- redrawing the
plate needs DejaVu Sans Mono on the machine doing it (`_FACES` in `splash.py`
names the file, `--font mono=/path/to/it` overrides, and `--stamp tt2` redraws
that line in Visitor instead if you would rather not depend on it).
