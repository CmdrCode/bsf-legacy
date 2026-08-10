# CLAUDE.md

Conventions for working in this repository.

Machine-local conventions — including everything governing what may be
published and how that is checked — live in `CLAUDE.local.md`, which is
untracked. Read it at the start of a session.

## What this repo may contain

BSF Legacy ships **no part of the game**. Behind every ignore pattern and both
hooks is one rule: nothing extracted from Battleships Forever, and nothing
generated from its source, is ever committed. **Ship the generator, never its
output.**

* `/_local/` is the private side folder — extracted material, files derived from
  the game's source, and the reverse-engineering notes. It is ignored *and* the
  `pre-commit` hook refuses staged paths under it, so a stray `git add -f`
  cannot get past both.
* `.gitignore` **is** the policy. The hook asks git (`git check-ignore
  --no-index`) rather than restating it as a second regex — an earlier duplicate
  had already drifted and let `*.dll` through. Every pattern added from now on
  is enforced for free.
* Nothing over 1 MB. This repo holds sources only.

## Git identity and pushing

Everything here is committed and pushed as `CmdrCode <CmdrCode@proton.me>`, over
this repo's SSH identity. Those pins are enforced by hooks rather than
assumed.

**The hazard this exists for:** ambient git credentials (the `gh` CLI, HTTPS
credential helpers) would misattribute a push made over an `https://` remote, so
this repo only ever pushes over its SSH alias.

### The four pins

| pin | where | value |
|---|---|---|
| SSH alias | `~/.ssh/config` | `Host github-bsf` → `github.com`, `IdentityFile ~/.ssh/id_ed25519_bsf`, `IdentitiesOnly yes` |
| remote | `.git/config` | `git@github-bsf:CmdrCode/bsf-legacy.git` — SSH via the alias, never HTTPS |
| identity | repo-local `user.name` / `user.email` | `CmdrCode` / `CmdrCode@proton.me` |
| signing | repo-local | `gpg.format ssh`, `user.signingkey ~/.ssh/id_ed25519_bsf.pub`, `commit.gpgsign true`, `tag.gpgsign true` |

`IdentitiesOnly yes` is load-bearing: it makes SSH offer `id_ed25519_bsf` and
nothing else, so GitHub binds the connection to this repo's identity rather than
to whatever a key search turns up first.

### The hooks

`core.hooksPath` points at `.githooks/`, which is **untracked** — the hooks are
per-machine, so a fresh clone does not get them. Once they are in place:

```bash
git config core.hooksPath "$(git rev-parse --show-toplevel)/.githooks"
```

**Set it absolute, not `.githooks`.** A relative value is resolved against the
working tree, and a linked worktree has no `.githooks/` — so every commit and
push made from a worktree silently runs with *no* hooks at all: no identity pin,
no `_local/` block, no ignore check, no size cap. Git reports nothing. An
absolute path is stored once in the shared config and covers every worktree.

Both hard-fail rather than warn.

* `pre-commit` — refuses any commit whose `user.name`/`user.email` are not the
  pinned identity; anything staged under `_local/`; anything `.gitignore`
  refuses; and any file over 1 MB.
* `pre-push` — refuses unless the remote is the SSH alias above, re-checks the
  **author and committer of every commit in the range**, and refuses if any
  `_local/` path is tracked.

**The pre-push hook is not a first line of defence.** Git negotiates with the
remote *before* the hook runs, so a wrong remote fails at authentication first
and the hook's message never appears. Get the remote right; the hook is the
backstop, not the guide.

### Before pushing

```bash
git remote -v                           # must be git@github-bsf:CmdrCode/...
git log --format='%an <%ae> | %G?' -3   # CmdrCode, and G
git push --dry-run                      # rehearses without sending
```

`%G?` must be `G` (good signature). `N` means the commit is unsigned and the
hooks let it through only because signing is a config setting, not a hook check
— amend with `git commit --amend --no-edit -S` rather than pushing it.

Never push this repository with `gh`, and never add an `https://` remote to it.

## Before publishing

This repo publishes under a single identity, and everything in it must be
usable by anyone who clones it. The rules that enforce both, and the script
that checks them, are machine-local and untracked by design.

**Read `CLAUDE.local.md` and follow it before every push.** Treat that as a
required step, not a reminder.

If it is not present in your checkout you do not have those rules, and a git
worktree never does — resolve it against the main checkout. Without it, work
freely but do not push.

## Skills

`.claude/skills/` holds the working knowledge for the three recurring jobs here.
Each is a runbook earned by trial and error, and each states how it may grow.

| skill | covers | evolution |
|---|---|---|
| `bsf-ships` | reading, editing, rendering, linting and live-previewing `.sb4`/`.shp` ships with `tools/bsf/ship.py` | folds learnings back automatically |
| `bsf-capture` | recording the game or ShipMaker under wine, driving it deterministically, encoding deliverables | folds learnings back automatically |
| `bsf-storytelling` | campaign voice, colours, Act II canon | **proposes** edits; updates only after approval |

`.claude/commands/` holds the slash commands for the repeated git flows.

## Modding

Every module is a plain GML text file, compiled at load by the game's own engine,
so it sees every game object, sprite and room by name exactly as the game's own
code does. GML cannot edit existing code in place, but it can append to an event
or replace one outright — which turns out to be enough for everything here.

Read `_local/research/MODDING-GUIDE.md` **before writing or debugging any
`mods/*.gml`.** It is the measured pitfall reference: the mod-loading and
silent-error regime, the dialect traps (`&&`/`||` never short-circuit; shadowing
a built-in constant silently kills the whole file; `real()` on a non-numeric
string aborts the action), event-append vs parent-shadowing, driving the game
from outside, and the pixel-exact drawing rules.

That guide and the rest of the engine library live in `_local/research/`, which
is untracked; `CLAUDE.local.md` indexes it.

## UI prototyping

When mocking or iterating on game UI — menus, HUD, screens — follow
`_local/UI-PROTOTYPING.md`: authentic-fidelity HTML mockups using the game's own
fonts and real cropped art, logical 1365×768 coordinates in container units,
headless-Chrome self-review against live captures, in-page variant pickers, and
the mock→GML mapping rules.
