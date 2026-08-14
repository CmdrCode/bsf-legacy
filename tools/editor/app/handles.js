/* Things you can grab on the map.
 *
 * The map has always drawn the mission's geometry in world coordinates and never
 * let you touch any of it, which is fine for beats — a beat is a moment, and you
 * edit it in the rail — but wrong for anything whose whole content is *where it
 * is*. A beacon, a scripted spawn, the player's start: reading coordinates out
 * of a card and typing new ones is describing a position, not editing it.
 *
 * So four kinds are draggable, and they are addressed rather than held: a drag
 * carries `{kind, i|bi, si}` and re-resolves the live object every move, because
 * an undo replaces the model's objects wholesale and a captured reference would
 * go on quietly mutating an orphan.
 *
 * Three things it must not do:
 *
 *  * It must not fight the storm brush. While the brush is up the map is a paint
 *    surface and every press belongs to it; this module stands down completely.
 *  * It must not make a beacon look like a per-beat thing. `gates:` is a mission
 *    list and a beat refers to one by index, so dragging beacon 2 moves it for
 *    every beat that waits on it. The rail says so next to the fields. A spawn
 *    is the opposite — it belongs to exactly one beat — so its label carries the
 *    beat it will fire on.
 *  * It must not silently edit a beat you cannot see. Every draggable thing is
 *    drawn on the map, including spawns from beats later than the playhead
 *    (dimmed); dragging one of those is legal and the label says which beat it
 *    is, because the alternative is a handle that is visible and dead.
 *
 * Not draggable, on purpose: the camera frame. Its centre is usually sitting on
 * top of the very things you are trying to grab — a station, the player — and a
 * 1024x768 rectangle is a hit target that swallows the map.
 */
window.Handles = (function () {
  'use strict';

  const css = `
.tl-view.grabbable canvas { cursor:grab; }
.tl-view.grabbing canvas { cursor:grabbing; }
`;

  /* World-space hit radius per kind, matched to what the map draws: a beacon's
     ring is 70 units, a spawn's bracket 60. */
  const R = { gate: 70, gate_at: 70, spawn: 60, player: 70, ping: 70 };

  /* Where a handle's coordinates live. Everything but a ping keeps them as
     `.x`/`.y` on an object; `ping:` is a two-element array, because a point is
     what it reads as in the YAML. One reader and one writer rather than a
     special case inside the drag. */
  const at = (t) => (Array.isArray(t) ? { x: t[0], y: t[1] } : t);
  function place(t, x, y) {
    if (Array.isArray(t)) { t[0] = x; t[1] = y; return; }
    t.x = x; t.y = y;
  }

  const H = {
    hover: null,      // address of the thing under the pointer, or null
    drag: null,       // { a, moved }
    refs: null,
  };

  const key = (a) => (a ? `${a.kind}:${a.i}:${a.bi}:${a.si}` : '');

  /* Every draggable thing, as an address plus where it is now. Rebuilt per hit
     test — it is a few dozen entries and the model changes under it constantly. */
  function list(m) {
    const out = [];
    (m.gates || []).forEach((g, i) => out.push({ kind: 'gate', i: i, x: g.x, y: g.y }));
    m.beats.forEach((b, bi) => {
      if (b.gate_at) out.push({ kind: 'gate_at', bi: bi, x: b.gate_at.x, y: b.gate_at.y });
      // Only a *fixed* ping. A linked one is drawn at the position of the spawn
      // it follows and has none of its own, so the thing to drag is that spawn —
      // offering a handle here would be offering to break the link by stealth.
      if (Array.isArray(b.ping)) out.push({ kind: 'ping', bi: bi, x: b.ping[0], y: b.ping[1] });
      (b.spawn || []).forEach((sp, si) =>
        out.push({ kind: 'spawn', bi: bi, si: si, x: sp.x, y: sp.y }));
    });
    // Address and position only. This list is rebuilt on every hit test, so on
    // every pointermove over the map — a label here would be a string built per
    // handle per move, and the one place a label is wanted (drawMap's, when a
    // handle is held) builds its own from the mission anyway.
    out.push({ kind: 'player', x: m.player.x, y: m.player.y });
    return out;
  }

  /* Address -> the live object with x and y on it. Null if the model moved on
     under a drag (an undo, a beat deleted), which ends the drag. */
  function resolve(m, a) {
    if (!a) return null;
    if (a.kind === 'gate') return (m.gates || [])[a.i];
    if (a.kind === 'gate_at') return (m.beats[a.bi] || {}).gate_at;
    if (a.kind === 'ping') {
      const p = (m.beats[a.bi] || {}).ping;
      return Array.isArray(p) ? p : null;      // linked under us: end the drag
    }
    if (a.kind === 'spawn') return ((m.beats[a.bi] || {}).spawn || [])[a.si];
    if (a.kind === 'player') return m.player;
    return null;
  }

  /* Nearest handle whose own radius contains the pointer. Zoomed out, 60 world
     units can be four pixels and a four-pixel target is not a target, so every
     radius has a screen floor — and the comparison is by *fraction* of radius so
     a tight target beats a loose one that happens to be marginally nearer. */
  function pick(w) {
    const k = (H.refs && H.refs.tr && H.refs.tr.k) || 1;
    let best = null, bestf = 1;
    list(App.mission).forEach((a) => {
      const r = Math.max(R[a.kind], 14 / k);
      const f = ((a.x - w.x) * (a.x - w.x) + (a.y - w.y) * (a.y - w.y)) / (r * r);
      if (f <= bestf) { bestf = f; best = a; }
    });
    return best;
  }

  function cursor() {
    const v = H.refs.cv.parentElement;
    v.classList.toggle('grabbable', !!H.hover && !H.drag);
    v.classList.toggle('grabbing', !!H.drag);
  }

  /* End the drag. Wired to window events like the brush's, and for the same
     reason: a `pointerup` delivered anywhere but here would otherwise leave a
     handle stuck to the pointer. A drag that never moved pops its own snapshot,
     so clicking a beacon to look at it does not cost a ctrl-Z. */
  function end() {
    if (H.drag && !H.drag.moved) Core.Model.undo(App.mission);
    if (H.drag) { H.drag = null; TL.drag(false); cursor(); App.emit('fields'); TL.paint(H.refs); }
  }

  function mount(refs) {
    H.refs = refs;

    refs.cv.addEventListener('pointerdown', (e) => {
      if (Paint.state.on) return;          // the brush owns the map while it is up
      if (e.button !== 0) return;
      const w = TL.world(refs, e);
      if (!w) return;
      const a = pick(w);
      if (!a) return;
      e.preventDefault();
      Core.Model.begin(App.mission);       // one drag, one undo step
      H.drag = { a: a, moved: false };
      try { refs.cv.setPointerCapture(e.pointerId); } catch (_) { /* nice to have */ }
      TL.drag(true);
      cursor();
    });

    refs.cv.addEventListener('pointermove', (e) => {
      if (Paint.state.on) return;
      // A pan drags the whole map under the pointer, so every handle it sweeps
      // over would light up and flip the cursor on its way past.
      if (View.panning()) return;
      const w = TL.world(refs, e);
      if (!w) return;
      if (H.drag && !e.buttons) return end();       // the release went missing
      if (H.drag) {
        const t = resolve(App.mission, H.drag.a);
        if (!t) return end();                       // the model moved under us
        const x = Math.max(0, Math.min(App.mission.room.width, Math.round(w.x)));
        const y = Math.max(0, Math.min(App.mission.room.height, Math.round(w.y)));
        const p = at(t);
        if (p.x === x && p.y === y) return;
        place(t, x, y);
        // The rail and the mission sheet both show coordinates, and neither
        // re-renders itself for an edit that came from the map — tell them,
        // every move, so the numbers track the drag instead of catching up at
        // the end.
        App.emit('fields');
        if (!H.drag.moved) { H.drag.moved = true; App.change(); }
        // Only a beacon reaches past the map: the gates lane prints its
        // coordinates in the span label (timeline.js spansOf). A spawn, a ping
        // or the player start changes nothing below the map, so the rest of the
        // chrome — lanes, message panel, YAML drawer — stays as it is.
        else TL[chromeDrag(H.drag.a) ? 'paint' : 'paintMap'](refs);
        return;
      }
      const a = pick(w);
      if (key(a) === key(H.hover)) return;          // repaint only when it changes
      H.hover = a;
      cursor();
      TL.paintMap(refs);                            // a highlight is map-only
    });

    refs.cv.addEventListener('pointerleave', () => {
      if (H.drag || !H.hover) return;
      H.hover = null; cursor(); TL.paintMap(refs);
    });

    addEventListener('pointerup', end);
    addEventListener('pointercancel', end);
    addEventListener('blur', end);
  }

  /* Does moving this show up anywhere but the map? Only a beacon does — its
     coordinates are printed in the gates lane's span label. */
  function chromeDrag(a) {
    return a.kind === 'gate' || a.kind === 'gate_at';
  }

  /* What drawMap needs to light the thing under the pointer. */
  function opts() {
    return { hover: H.drag ? H.drag.a : H.hover };
  }

  return { css, mount, opts, state: H };
})();
