#!/bin/bash
# Shared helpers for BSF capture driver scripts. Source this file, then set
# GAME to the scratch copy of the game dir before using the probe helpers.
# Extracted from the proven 4K driver (_local/captures/drive-capture.sh).
#
# Usage sketch:
#   source "$(dirname "$0")/drive-lib.sh"
#   GAME=/path/to/scratch/bsf-cap
#   focus_game || exit 1
#   to_main_menu || { echo "could not reach main menu"; exit 1; }
#   glide 2991 1377; touch "$GAME/mods/optreq"; sleep 3.5
#   key Right

export DISPLAY=${DISPLAY:-:0}

say() { echo "[$(date +%T.%1N)] $*"; }

# The WM only knows the outer wine-desktop window; target its stable title.
# Raising the inner game window does nothing (title changes with the room).
focus_game() { wmctrl -a 'Wine desktop'; }

# glide X Y — move the mouse there smoothly over ~1s. Cosmetic: position DOES
# track in-game, clicks would not.
glide() {
  local tx=$1 ty=$2 X Y NX NY i
  eval "$(xdotool getmouselocation --shell 2>/dev/null | grep -E '^(X|Y)=')"
  for i in $(seq 1 24); do
    NX=$(( X + (tx - X) * i / 24 )); NY=$(( Y + (ty - Y) * i / 24 ))
    xdotool mousemove "$NX" "$NY"; sleep 0.04
  done
}

# key KEYSYM — refocus, then send one key. Rule: refocus before EVERY key;
# the user's terminal often sits above the wine desktop.
key() { focus_game; xdotool key --clearmodifiers "$1"; }

# wait_probe REGEX [TRIES] — wait until mods/probe.txt matches, ~1s per try.
wait_probe() {
  local re=$1 tries=${2:-10} i
  for (( i=0; i<tries; i++ )); do
    grep -q "$re" "$GAME/mods/probe.txt" 2>/dev/null && return 0
    sleep 1
  done
  return 1
}

# to_main_menu — Escape until the probe reports room=1 (the main menu).
to_main_menu() {
  local i
  for i in 1 2 3; do
    grep -q '^room=1 ' "$GAME/mods/probe.txt" 2>/dev/null && return 0
    say "not on main menu, sending Escape"; key Escape; sleep 2
  done
  grep -q '^room=1 ' "$GAME/mods/probe.txt"
}
