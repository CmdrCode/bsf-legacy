---
allowed-tools: Bash(git:*), Bash(python3:*), Bash(tools/build.sh:*), Bash(mktemp:*), Bash(cd:*), Bash(test:*)
description: Commit worktree changes, merge main into this branch, run the local gates (py_compile, installer smoke, DLL build if touched), push HEAD to origin/main, and fast-forward local main to match
---

# Git Commit + Merge Worktree

Argument (optional commit message): `$ARGUMENTS`

Chains together the common "ship this worktree" flow:

1. Commit any local changes in the current worktree.
2. Merge `main` into this branch (fast-forward, or a merge commit if diverged).
3. Run the local gates so a broken tree never reaches `origin/main`.
4. Push `HEAD` to `origin/main` (fast-forward only — no `--force`).
5. Fast-forward the local `main` ref so it matches `origin/main`.

If any step produces an unexpected state (conflicts, non-fast-forward, detached HEAD, failing gates, etc.) **STOP** and report the state. Never use `--force`, `--no-verify`, `reset --hard`, or rewrite history.

## Step 1 — Commit local changes

Run these in parallel:
- `git status --porcelain`
- `git diff HEAD`
- `git log --oneline -10` (to match local commit style)

Then:

- **If `git status --porcelain` is empty**: skip to Step 2.
- **If there are merge conflicts** (lines starting with `UU`, `AA`, `DD`, `AU`, `UA`, `DU`, `UD`): **STOP**. Report the conflicted files and ask the user to resolve.
- **Otherwise**:
  - **If `$ARGUMENTS` is non-empty**: use it as the commit title verbatim.
  - **Otherwise**: draft a 1–2 sentence commit message from the diff, matching the style of recent `git log` entries (imperative, capitalized first word, short title).
  - Stage only the files reported by `git status --porcelain` (named explicitly — do NOT use `git add -A` or `git add .`).
  - **Use judgement on what belongs in the commit — a dirty file is not automatically intentional work.** This repo's cardinal rule: **nothing extracted from the game or derived from its source may ever be committed** — the game itself (`*.exe`, `*.dll`, `*.gmk`), anything under `_local/`, decompiled dumps, and the generated GML modules listed in `.gitignore`. The `.gitignore` and the `.githooks/pre-commit` hook both refuse these, but do not lean on them: never `git add -f` past an ignore rule, and leave anything game-derived or suspicious unstaged and say so in the summary. Runtime state the mods write next to themselves (`mods/*.on`, `*.log`, `*.txt`, `*.cfg`) is machine-local, not work.
  - **Skip files that may contain secrets** (`.env`, `*.pem`, `credentials*`, `*.key`). Warn the user if any are in the change set and wait for explicit authorization.
  - Commit using a HEREDOC. **This repo's history carries no `Co-Authored-By` trailer** — match that: title and optional body only, no trailer.
    ```
    git commit -m "$(cat <<'EOF'
    <title>

    <optional body>
    EOF
    )"
    ```
  - If the pre-commit hook fails: investigate the root cause, fix it, re-stage, and create a NEW commit. **Do NOT** use `--amend` or `--no-verify`.

## Step 2 — Merge main into this branch

- If the current branch IS `main`, **STOP** — this flow is for worktree/feature branches.
- Run `git fetch origin main` so the comparison against the remote is current.
- **Check that local `main` is not stale before merging it.** This step merges the **local `main` ref** — that is deliberate, so that whatever the human has staged locally on `main` ships with this run. But Step 4 pushes against `origin/main`, and nothing keeps the local ref current except Step 5 of a *previous* run. If the two have drifted, you merge an outdated `main` and then Step 4 refuses to push — leaving a merge commit already created and the branch half-shipped.
  ```
  git log main..origin/main --oneline
  ```
  - **Empty** — local `main` is current (or ahead). Continue; merge local `main` as normal.
  - **Non-empty** — local `main` is behind the remote. Fast-forward the local ref first using the Step 5 mechanics (`git -C <main-worktree> merge --ff-only origin/main`, or `git update-ref` when headless), then continue. If that fast-forward is refused, **STOP** and report — do not merge a stale `main`.
- Run `git log HEAD..main --oneline`.
- **If the output is empty**: local `main` has nothing new for this branch — skip to Step 3.
- Otherwise, before merging, check whether any incoming commits touch files that are about to conflict. Not required, but surfaces overlap early:
  ```
  git log HEAD..main --name-only --pretty=format:
  ```
- Run `git merge main --no-edit`.
  - **On fast-forward**: continue to Step 3.
  - **On conflict**: **STOP**. Report the conflicted files and exit. Do NOT run `git merge --abort` automatically — leave the state for the user to resolve.
  - **If a non-fast-forward merge commit would be created** (i.e., this branch has diverged from main): accept the merge commit that `--no-edit` produces, but report it explicitly so the user knows a merge commit was created.

## Step 3 — Run the local gates

Always run the gates on the post-commit, post-merge tree. They are all quick (seconds); run them sequentially so a failure is unambiguous.

- **Skip entirely only if nothing changed**: if Step 1 committed nothing AND Step 2 merged nothing, there is nothing new to test — skip to Step 4.

### Gate 1 — Python syntax

```
python3 -m py_compile tools/*.py
```

Every tool in one shot. Catches syntax errors in the patcher, generators, and installer.

### Gate 2 — Installer smoke (local mirror of the CI contract)

CI's smoke test asserts: the installer, finding no game, must print `Could not find BattleshipsForever.exe` and exit **1** — that nonzero exit is the contract for the not-found path. Reproduce it locally:

- **Safety check first**: `test ! -e tools/BattleshipsForever.exe` — `install.py` searches the directory containing the script before the cwd, so a game exe sitting in `tools/` would get **patched for real** instead of exercising the not-found path. If one is present, **STOP** and report.
- Run from an empty scratch directory so no candidate dir contains a game:
  ```
  t="$(git rev-parse --show-toplevel)/tools/install.py"
  d="$(mktemp -d)" && (cd "$d" && python3 "$t"); echo "exit=$?"
  ```
  (`--show-toplevel` resolves to the current worktree's root, which is the point — the gate must run the tree being shipped, not whichever copy sits at a fixed path.)
- **Pass**: output contains `Could not find BattleshipsForever.exe` AND exit code is `1`.
- Any other outcome (exit 0, a traceback, a different message) is a failure of the tree being shipped.

### Gate 3 — Native DLL build (only when touched)

Only if `git diff --name-only origin/main...HEAD` includes `tools/bsfnat.c` or `tools/build.sh`:

```
tools/build.sh
```

Needs an i686 mingw compiler (`gcc-mingw-w64-i686`, or `MINGW_PREFIX`). The produced `bsfnat.dll` is git-ignored, so rebuilding is safe. **If no compiler is available**, report the gate as skipped-for-environment in the summary — do not silently pass it.

### Not covered locally

The PyInstaller exe build + smoke runs only in CI (`.github/workflows/build-installer.yml`, on `workflow_dispatch` or a `v*` tag) — it needs a real Windows runner. If the branch touched `tools/install.py`, its imports, or the workflow itself, say in the summary that the frozen-exe path (hidden imports, `--add-data`) remains unverified until the next CI run.

### On failure

**STOP before pushing and triage.** For each failure decide:

- **Real regression** (this branch broke it) → must fix before pushing. Investigate, fix, commit a **NEW** commit (never `--amend`/`--no-verify`), and re-run the gates.
- **Environmental** (missing mingw, missing python3) → report the skip explicitly.

**Do NOT push over any non-green result without the human's go-ahead.**

## Step 4 — Push HEAD to origin/main

- Run `git fetch origin main` (again, in case the remote moved during Steps 2–3).
- Run `git log origin/main..HEAD --oneline` and `git log HEAD..origin/main --oneline`.
- **If `HEAD..origin/main` is non-empty**: the remote `main` has commits this branch doesn't contain. **STOP** and report — the user must decide whether to rebase, merge, or accept the divergence before pushing.
- **If `origin/main..HEAD` is empty**: nothing to push — report "Already up to date with origin/main." and exit.
- **Otherwise**: run `git push origin HEAD:main` (no `--force`, no `--force-with-lease`). The push will refuse if it isn't a fast-forward; that refusal is the intended safety net.

## Step 5 — Fast-forward local `main` to `origin/main`

After a successful push, the remote `main` has advanced but the local `main` branch ref is still where it was. Update it so a future `git log main` or fresh worktree sees the new commits.

- Run `git worktree list --porcelain` and find the line `branch refs/heads/main` — record the `worktree <path>` above it.
- **If `main` is checked out in a worktree**: run `git -C <that-path> merge --ff-only origin/main`.
  - Fast-forward merges only touch files that actually changed; if that worktree has unrelated dirty files it will usually succeed, but if git refuses (conflict with uncommitted work in the main worktree), **STOP** and report. Do NOT force, stash, or discard anything in that worktree.
- **If `main` is not checked out anywhere** (headless): run `git update-ref refs/heads/main refs/remotes/origin/main`. Safe — no working tree affected.
- **Skip this step** if Step 4 reported "Already up to date with origin/main" (local `main` may still be behind, but that's outside this run's scope — surface it in the final summary so the user knows).

## Final summary

After a successful run, report:
- Commit hash created (if any) and its one-line title.
- Whether Step 2 was a fast-forward, a no-op, or produced a merge commit.
- Anything left deliberately unstaged in Step 1 (game-derived files, runtime state, suspicious files) and why.
- Gate results — py_compile, installer smoke, DLL build — passed, skipped (with the reason), or triaged.
- Whether the frozen-exe CI path remains unverified for this change.
- The range pushed in Step 4 (e.g., `47aab5b..a1b2c3d  HEAD -> main`).
- Whether local `main` was fast-forwarded in Step 5, and where it was updated (worktree path or headless ref).

Keep the final report under 12 lines.
