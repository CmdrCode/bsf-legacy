/* Zoom and pan on the map.
 *
 * The map was always fitted to its element: a 5000x2000 room in a panel a few
 * hundred pixels tall puts the whole mission on screen at roughly a tenth
 * scale, which is right for reading a route and useless for placing anything.
 * A berthed hull is 190 units long — two pixels — so the four wrecks at the
 * Bolthole gantry were a smudge you could drag but not aim.
 *
 * Two things make this cheap. `drawMap` already took `zoom` and `center` and
 * already returned the transform it drew with, and every tool that grabs
 * something on the map goes through `TL.world`, which inverts that same
 * transform. So nothing downstream — handles, the storm brush, the ghost
 * overlay — has to know this module exists.
 *
 * The rules it does own:
 *
 *  * **Zoom is anchored to the pointer**, not the centre. The world point under
 *    the cursor stays under the cursor, which is the only behaviour that lets
 *    you zoom *at* something rather than zoom and then go looking for it.
 *  * **Fit is the floor.** Zooming out stops at the framing the map had before
 *    this module existed, and lands back on it exactly — at zoom 1 the centre
 *    is dropped and `drawMap` takes its own fit path again.
 *  * **The room cannot be pushed off screen.** The centre is held inside the
 *    room — the weakest bound that still makes losing the mission impossible,
 *    and the strongest one the anchor survives. See `clampCentre`.
 *  * **Left-drag pans only what nothing else wanted.** The brush owns the map
 *    while it is up, and a press that grabbed a handle is a handle drag; the
 *    pan is what is left, and only while zoomed in, so at fit the map behaves
 *    exactly as it always did. The middle button pans regardless — it is the
 *    way out of a corner without putting the brush away.
 */
window.View = (function () {
  'use strict';

  const css = `
.tl-view.panning canvas { cursor:grabbing; }
`;

  const MIN = 1, MAX = 24;

  const V = {
    zoom: 1,
    center: null,     // world point held at the canvas centre; null = fit the room
    refs: null,
    pan: null,        // { x, y } — the last pointer position, in client pixels
  };

  const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);

  /* The scale `drawMap` would use at zoom 1. Read from the last transform
     rather than recomputed, because the fit depends on the padding the caller
     chose and on the element's live size — both of which this module would be
     guessing at. */
  function fitK() {
    const t = V.refs && V.refs.tr;
    return t && t.fit ? t.fit : null;
  }

  /* The centre may go anywhere inside the room and nowhere outside it: weak
     enough to allow dead space along an edge, which is the price of the anchor
     holding exactly, and strong enough that the mission can never be flicked
     off the screen.

     The stronger rule — keep the room *covering* the canvas — was tried first
     and is wrong here. A 5000x2000 room in a wide panel is letterboxed at the
     fit, so on the slack axis "cover the canvas" means "stay centred", and the
     point under the cursor lurched by the slack as it closed: measured at 160
     world units on the first notch. Anchoring is the feature; the clamp is a
     backstop, and a backstop does not get to move the thing you aimed at.

     What is left is exact: measured zero drift for any point *inside the room*,
     at all four of its corners, from the fit to the ceiling. Aim at the
     letterbox outside the room and the clamp does win — you asked to centre on
     something that is not the mission — and that is the only case where it
     does. */
  function clampCentre() {
    const m = window.App && App.mission;
    if (!m || !V.center) return;
    V.center.x = clamp(V.center.x, 0, m.room.width);
    V.center.y = clamp(V.center.y, 0, m.room.height);
  }

  /* Go to `z`, holding the world point at canvas pixel (px, py) under that same
     pixel. The anchor point is derived here rather than passed in: it is the
     module's whole invariant, and a caller that inverted the transform itself
     could hand over a point from a stale one.

     At the floor the centre is dropped entirely, so zooming all the way out
     returns the exact framing the map had before anyone touched the wheel —
     even if the view was panned when it got there. */
  function zoomTo(z, px, py) {
    const f = fitK(), w = TL.worldAt(V.refs, px, py);
    if (!f || !w) return;
    z = clamp(z, MIN, MAX);
    if (z === V.zoom) return;
    V.zoom = z;
    if (z <= MIN) V.center = null;
    else {
      const cv = V.refs.cv, k = f * z;
      V.center = { x: w.x + (cv.clientWidth / 2 - px) / k,
        y: w.y + (cv.clientHeight / 2 - py) / k };
      clampCentre();
    }
    TL.paintMap(V.refs);
  }

  /* Zoom about the middle of the canvas — what the keys use, since they have no
     pointer to anchor to. */
  function zoomBy(factor) {
    const cv = V.refs && V.refs.cv;
    if (!cv) return;
    zoomTo(V.zoom * factor, cv.clientWidth / 2, cv.clientHeight / 2);
  }

  /* The framing this module hands back to `drawMap`'s own fit path. `reset` is
     the state change alone: a mission load re-renders everything anyway, and
     painting here as well would draw the new room at the old zoom first. */
  function reset() { V.zoom = 1; V.center = null; }

  function fit() {
    reset();
    if (V.refs) TL.paintMap(V.refs);
  }

  /* Held for the whole pan. The end is wired to the window rather than to the
     canvas for the reason paint.js spells out: a release delivered anywhere
     else would otherwise leave the map stuck to the pointer. */
  function endPan() {
    if (!V.pan) return;
    V.pan = null;
    V.refs.cv.parentElement.classList.remove('panning');
    TL.drag(false);
  }

  function mount(refs) {
    V.refs = refs;

    refs.cv.addEventListener('wheel', (e) => {
      if (!refs.tr || !App.mission) return;
      // Not passive: the page must not zoom under a ctrl-wheel and the map must
      // not scroll anything behind it.
      e.preventDefault();
      // deltaMode 1 is lines and 2 is pages; normalise both to pixels so a
      // Firefox notch and a Chrome notch mean the same thing.
      const dy = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaMode === 2 ? e.deltaY * 400 : e.deltaY;
      // A trackpad pinch arrives as ctrl+wheel with a far smaller delta than a
      // wheel notch, so it needs its own coefficient or a pinch moves nothing.
      const step = Math.exp(-dy * (e.ctrlKey ? 0.012 : 0.0016));
      const r = refs.cv.getBoundingClientRect();
      zoomTo(V.zoom * step, e.clientX - r.left, e.clientY - r.top);
    }, { passive: false });

    // Chrome opens its autoscroll widget on a middle press unless the default is
    // taken away, and pointerdown is too late for that one.
    refs.cv.addEventListener('mousedown', (e) => { if (e.button === 1) e.preventDefault(); });

    // Mounted after paint.js and handles.js, which is what makes this readable:
    // by the time this runs, a press that grabbed a handle has already said so.
    refs.cv.addEventListener('pointerdown', (e) => {
      if (V.zoom <= MIN) return;                    // nothing to pan at fit
      const middle = e.button === 1;
      if (!middle) {
        if (e.button !== 0) return;
        if (Paint.state.on) return;                 // the brush owns the map
        if (Handles.state.drag) return;             // that press was a handle
      }
      e.preventDefault();
      V.pan = { x: e.clientX, y: e.clientY };
      try { refs.cv.setPointerCapture(e.pointerId); } catch (_) { /* nice to have */ }
      refs.cv.parentElement.classList.add('panning');
      TL.drag(true);
    });

    refs.cv.addEventListener('pointermove', (e) => {
      if (!V.pan) return;
      if (!e.buttons) return endPan();              // the release went missing
      const t = refs.tr;
      if (!t || !V.center) return;
      // Incremental, not anchored to the press: a pan that runs into the clamp
      // and comes back should follow the pointer again immediately rather than
      // paying back the distance it could not travel.
      const cx = V.center.x, cy = V.center.y;
      V.center.x -= (e.clientX - V.pan.x) / t.k;
      V.center.y -= (e.clientY - V.pan.y) / t.k;
      V.pan = { x: e.clientX, y: e.clientY };
      clampCentre();
      // Held against the clamp at a room edge: the pointer moved, the map did
      // not, and repainting an identical frame per pointer event is pure waste.
      if (V.center.x === cx && V.center.y === cy) return;
      TL.paintMap(refs);
    });

    addEventListener('pointerup', endPan);
    addEventListener('pointercancel', endPan);
    addEventListener('blur', endPan);
  }

  function key(e) {
    if (e.key === '0') { fit(); return true; }
    if (e.key === '+' || e.key === '=') { zoomBy(1.3); return true; }
    if (e.key === '-' || e.key === '_') { zoomBy(1 / 1.3); return true; }
    return false;
  }

  /* What drawMap needs to frame it, and what the rest of the chrome asks. */
  function opts() { return { zoom: V.zoom, center: V.center }; }
  function panning() { return !!V.pan; }
  function zoomed() { return V.zoom > MIN; }
  function label() { return '×' + (V.zoom < 10 ? V.zoom.toFixed(1) : Math.round(V.zoom)); }

  return { css, mount, key, opts, fit, reset, panning, zoomed, label, state: V };
})();
