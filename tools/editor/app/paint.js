/* The storm brush.
 *
 * A storm is a painted mask, so the editor has to be somewhere you can paint —
 * and the only surface in this editor drawn in world coordinates is the map. The
 * brush therefore lives on the map canvas and nowhere else: press to paint, drag
 * to keep painting, alt or the right button to erase.
 *
 * Two things make it behave like a paint tool rather than like a form:
 *
 *  * One drag is one undo step. Model.begin() snapshots on pointerdown, and the
 *    strokes in between only mutate — otherwise ctrl-Z would walk back through a
 *    drag one pointermove at a time and never reach the state before it.
 *  * The brush is round in CELLS, not in pixels. The mask is the unit of truth
 *    (it is what the game reads and what the file shows), so zooming must not
 *    change what a click does.
 *
 * The tool takes over the map's pointer while it is up, which is why it is a
 * mode with a visible panel and not an invisible modifier: the map is otherwise
 * a read-only view, and a stray click on it should never silently edit a
 * mission.
 */
window.Paint = (function () {
  'use strict';

  const css = `
.pt { position:absolute; left:12px; bottom:12px; z-index:6; background:rgba(8,13,14,.94);
      border:1px solid var(--rule); border-radius:2px; padding:8px 10px; display:none;
      font:10px/1.6 var(--mono); color:var(--ink-dim); user-select:none; }
.pt.on { display:block; }
.pt h6 { margin:0 0 6px; font:9.5px/1 var(--mono); letter-spacing:.16em; text-transform:uppercase; color:var(--hostile); }
.pt .row { display:flex; align-items:center; gap:5px; margin-top:4px; }
.pt .row > span.l { width:52px; color:#3f5a55; letter-spacing:.08em; text-transform:uppercase; font-size:9px; }
.pt button { all:unset; cursor:pointer; padding:3px 7px; border:1px solid var(--rule); border-radius:2px;
             color:var(--ink-dim); font:9.5px/1 var(--mono); }
.pt button:hover { border-color:var(--phos); color:var(--phos); }
.pt button.on { border-color:var(--hostile); color:var(--hostile); }
.pt button.on.hot { border-color:var(--amber); color:var(--amber); }
.pt button.on.era { border-color:var(--ghost); color:var(--ghost); }
.pt .hint { margin-top:7px; color:#3f5a55; max-width:250px; line-height:1.5; }
.pt input { font:10px/1.4 var(--mono); background:#070d0e; color:var(--ink); width:56px;
            border:1px solid var(--rule); border-radius:2px; padding:2px 4px; }
.pt input:focus { outline:none; border-color:var(--phos); }
.pt b { color:var(--ink); font-weight:400; }
.tl-view.painting canvas { cursor:crosshair; }
`;

  const P = {
    on: false,
    radius: 3,
    level: 1,          // 1 = '#' at storm.dmg, 2 = '@' at storm.hot
    erase: false,
    at: null,          // brush centre in world units, for the ring on the map
    stroke: null,      // the drag in progress, if any
    refs: null,
  };

  /* End the drag in progress. Safe to call at any time and from anywhere — it is
     wired to window events that fire constantly — because with no stroke open it
     does nothing. A stroke that never changed a cell pops its own undo snapshot
     again, so a click that missed does not cost a ctrl-Z. */
  function end() {
    if (P.stroke && !P.stroke.dirty) Core.Model.undo(App.mission);
    P.stroke = null;
  }

  const world = (e) => TL.world(P.refs, e);

  function panel() {
    const el = P.refs.root.querySelector('.pt');
    if (!el) return;
    el.classList.toggle('on', P.on);
    el.querySelector('.rad').textContent = P.radius;
    el.querySelectorAll('[data-lv]').forEach((b) =>
      b.classList.toggle('on', !P.erase && +b.dataset.lv === P.level));
    el.querySelector('[data-era]').classList.toggle('on', P.erase);
    const m = App.mission, st = m.storm || {};
    el.querySelector('.dmg').textContent = P.erase ? 'clear'
      : P.level === 2 ? `@  −${st.hot} hp/step` : `#  −${st.dmg} hp/step`;
    // Never while the field has focus, or typing "0.2" is fought at the "0."
    el.querySelectorAll('input[data-s]').forEach((f) => {
      if (f !== document.activeElement) f.value = st[f.dataset.s];
    });
  }

  /* The *map*, not the chrome. Nothing the brush does between App.change()es
     can alter the track, the lanes, the message panel or the YAML drawer — and
     the drawer re-serialises the whole mission through Core.toYaml, which is
     not something to do on every pointermove. */
  function repaint() { TL.paintMap(P.refs); }

  function set(k, v) { P[k] = v; panel(); repaint(); }

  function toggle(on) {
    end();                               // never leave a stroke open behind the tool
    P.on = on == null ? !P.on : !!on;
    if (P.on) Core.Storm.ensure(App.mission);
    P.at = null;
    P.refs.cv.parentElement.classList.toggle('painting', P.on);
    panel();
    repaint();
    return P.on;
  }

  function mount(refs) {
    P.refs = refs;
    const view = refs.cv.parentElement;
    const el = document.createElement('div');
    el.className = 'pt';
    el.innerHTML = `<h6>storm brush</h6>
      <div class="row"><span class="l">paint</span>
        <button data-lv="1">#  cell</button><button data-lv="2" class="hot">@  hot</button>
        <button data-era="1" class="era">erase</button></div>
      <div class="row"><span class="l">brush</span>
        <button data-r="-1">−</button><b class="rad">3</b><button data-r="1">+</button>
        <span style="margin-left:6px" class="dmg"></span></div>
      <div class="row"><span class="l">hp/step</span>
        <input data-s="dmg" step="0.05"> <input data-s="hot" step="0.05"></div>
      <div class="row"><span class="l">clouds</span>
        <input data-s="density" step="0.02" title="gas-cloud puffs per filled cell">
        <input data-s="lightning" step="10" title="average frames between strikes; 0 = none"></div>
      <div class="hint">drag on the map to paint · <b>alt</b> or right button erases ·
        <b>[</b> <b>]</b> size · <b>1</b> <b>2</b> <b>e</b> tool · <b>b</b> puts the brush away</div>`;
    view.appendChild(el);

    el.addEventListener('pointerdown', (e) => e.stopPropagation());
    el.addEventListener('focusin', (e) => { if (e.target.matches('input')) Core.Model.begin(App.mission); });
    el.addEventListener('input', (e) => {
      const k = e.target.dataset.s;
      if (!k) return;
      const v = Number(e.target.value);
      if (!isFinite(v)) return;
      Core.Storm.ensure(App.mission)[k] = v;
      App.change();
      panel();
    });
    el.addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (!b) return;
      if (b.dataset.lv) { P.erase = false; set('level', +b.dataset.lv); }
      if (b.dataset.era) set('erase', true);
      if (b.dataset.r) set('radius', Math.max(1, Math.min(20, P.radius + +b.dataset.r)));
    });

    // ---- the stroke
    //
    // A stroke ends on a `pointerup` that this code is NOT allowed to assume it
    // will receive on the canvas. `setPointerCapture` is supposed to guarantee
    // exactly that, and it holds for a press-drag-release that stays inside the
    // page — but not for every real one: released past the edge of the window,
    // capture dropped, the window blurred mid-drag. Miss that single event with
    // the end listener on the canvas and `stroke` is never cleared, so every
    // later mouse move over the map keeps painting with no button held. That is
    // the whole of the "you can't stop painting" bug, and it is why the ends are
    // on the *window* — the same thing the beat drag and the ruler scrub do —
    // with capture demoted to an optimisation.
    //
    // The backstop needs no event at all: a `pointermove` reporting `buttons`
    // of 0 is proof no button is down, whatever happened to the release.
    refs.cv.addEventListener('pointerdown', (e) => {
      if (!P.on) return;
      if (e.button !== 0 && e.button !== 2) return;      // left paints, right erases
      e.preventDefault();
      const w = world(e);
      if (!w) return;
      // Snapshot once, here: everything from now until the release is one edit.
      Core.Model.begin(App.mission);
      P.stroke = { erase: P.erase || e.altKey || e.button === 2, dirty: false };
      try { refs.cv.setPointerCapture(e.pointerId); } catch (_) { /* nice to have */ }
      draw(w, P.stroke);
    });
    refs.cv.addEventListener('pointermove', (e) => {
      if (!P.on) return;
      if (P.stroke && !e.buttons) end();                 // the release went missing
      const w = world(e);
      if (!w) return;
      const prev = P.at;
      P.at = w;
      if (P.stroke) { draw(w, P.stroke); return; }
      // The ring is snapped to the cell, so a move inside one cell redraws a
      // byte-identical frame. Compare cells, not pixels.
      const cell = Core.Storm.cell(App.mission);
      if (prev && Math.floor(prev.x / cell) === Math.floor(w.x / cell)
               && Math.floor(prev.y / cell) === Math.floor(w.y / cell)) return;
      repaint();
    });
    addEventListener('pointerup', end);
    addEventListener('pointercancel', end);
    addEventListener('blur', end);
    refs.cv.addEventListener('pointerleave', () => { if (!P.stroke) { P.at = null; repaint(); } });
    refs.cv.addEventListener('contextmenu', (e) => { if (P.on) e.preventDefault(); });

    // App.change() re-lints and repaints the whole chrome, which is right once
    // per stroke and waste sixty times a second — so only the first cell of a
    // drag goes through it, and the rest just redraw the map.
    function draw(w, st) {
      if (!st) return;
      const hit = Core.Storm.paint(App.mission, w.x, w.y, P.radius, st.erase ? 0 : P.level);
      if (hit && !st.dirty) { st.dirty = true; App.change(); }
      else repaint();
    }

    panel();
  }

  /* What drawMap needs to draw the grid and the brush ring. */
  function opts() {
    return P.on ? { at: P.at, radius: P.radius, level: P.level, erase: P.erase } : null;
  }

  function key(e) {
    if (e.key === 'b') { toggle(); return true; }
    if (!P.on) return false;
    if (e.key === '[') { set('radius', Math.max(1, P.radius - 1)); return true; }
    if (e.key === ']') { set('radius', Math.min(20, P.radius + 1)); return true; }
    if (e.key === '1') { P.erase = false; set('level', 1); return true; }
    if (e.key === '2') { P.erase = false; set('level', 2); return true; }
    if (e.key === 'e') { set('erase', !P.erase); return true; }
    if (e.key === 'Escape') { toggle(false); return true; }
    return false;
  }

  return { css, mount, toggle, opts, key, state: P };
})();
