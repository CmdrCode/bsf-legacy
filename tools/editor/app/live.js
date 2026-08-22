/* The running game, as seen from the editor.
 *
 * Two rules from the design, and everything here is one of them:
 *
 *  1. **Control direction flips with the pause state.** Paused, the editor drives
 *     the game: selecting a beat seeks. Playing, the game drives the editor: the
 *     playhead follows the beat tracer. Clicking a beat while playing pauses
 *     first, then seeks — one rule, no mode to remember.
 *  2. **The truth loop is a ghost overlay.** After every settle the game's own
 *     instance dump is drawn over the prediction in the same coordinates. A
 *     matched instance sits on its prediction, a missing one leaves a prediction
 *     with no ghost, a drifted one shows the offset as a line. There is no
 *     "is it right?" to reason about — you look.
 *
 * Seeking is directional. The generated ladder is cumulative, so a backward seek
 * would re-run earlier rungs and duplicate every spawn; the server turns one into
 * a warm re-entry plus a forward seek, which is why a step back costs a second
 * and a step forward costs a frame.
 */
window.Live = (function () {
  'use strict';

  const L = {
    running: false, inMission: false, state: null, dump: null,
    mode: 'off',                       // off | ghosts — the overlay toggle
    busy: false,
    onchange: null,
    _timer: null, _seq: -1,
  };

  const post = (url, body) =>
    fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}) }).then((r) => r.json());

  // ------------------------------------------------------------------ poll
  // Fast enough that the playhead tracks dialogue, slow enough to be free: the
  // game writes mods/edit/state every ten steps and at once on a beat change, so
  // polling faster than that only re-reads the same file.
  L.start = function () {
    if (L._timer) return;
    const tick = () => {
      const want = L.mode === 'ghosts' ? '?ghosts=1' : '';
      fetch('api/live' + want).then((r) => r.json()).then((d) => {
        const was = L.running, wasSeq = L.state && L.state.beatseq;
        L.running = !!d.running;
        L.inMission = !!d.inMission;
        L.state = d.state || null;
        if (d.dump) L.dump = d.dump;
        if (!L.running) L.dump = null;
        const seq = L.state && L.state.beatseq;
        if (L.onchange) L.onchange({ ranChanged: was !== L.running, beatChanged: seq !== wasSeq });
      }).catch(() => { }).finally(() => { L._timer = setTimeout(tick, 400); });
    };
    tick();
  };

  // --------------------------------------------------------------- control
  L.launch = (mission) => { L.busy = true; return post('api/launch', { mission }).finally(() => (L.busy = false)); };
  L.stop = () => post('api/stop');
  L.cmd = (cmd) => post('api/cmd', { cmd });

  L.paused = () => !!(L.state && L.state.pause);
  L.editRules = () => !!(L.state && L.state.edit);

  L.setPause = (on) => L.cmd('pause ' + (on ? 1 : 0));
  L.setEdit = (on) => L.cmd('edit ' + (on ? 1 : 0));

  /* Put the game at the beat the editor is showing. The server pauses first and
     dumps afterwards — both are part of seeking, not of asking for a seek. */
  L.goto = function (rung, mission) {
    if (!L.running || !L.inMission) return Promise.resolve(null);
    L.busy = true;
    return post('api/goto', { rung, mission }).finally(() => { L.busy = false; });
  };

  /* Which beat index the game is sitting on, or -1. The tracer publishes a RUNG
     number, and rungs skip — a `wait: gate` beat reserves the next slot for the
     gate's own +1 — so it has to be looked up, never divided. */
  L.beatIndex = function (m) {
    if (!L.inMission || !L.state || !m) return -1;
    const rung = L.state.beat;
    if (rung == null || rung < 0) return -1;
    // `.rung` and not `.n`: the start beat's `n` is the string 'start' (it is
    // what the ruler prints), while the game only ever publishes numbers. The
    // two are the same field for every other beat, which is exactly why mixing
    // them up survives until the playhead reaches beat 0 and stops following.
    const numbered = Core.numberBeats(m);
    for (let i = 0; i < numbered.length; i++) if (numbered[i].rung === rung) return i;
    return -1;
  };

  L.viewNote = function (zoom) {
    // The room's authored view is 1024x768, but the resolution mod rewrites the
    // ports at run time — a live dump came back 3140x1766 — so the frame drawn
    // over the map is the game's real view whenever there is one to read.
    const h = L.dump && L.dump.head;
    if (!h || !h.vieww) {
      // With no game to read, the box is the authored view scaled by whatever
      // zoom the beat left in force — say which, because "1024×768" over a
      // zoomed beat is a caption that disagrees with the box beside it.
      const z = zoom == null ? 1 : zoom;
      return z === 1 ? ' · dashed box = the 1024×768 view'
        : ` · dashed box = the ${Math.round(1024 * z)}×${Math.round(768 * z)} view at zoom ${z}`;
    }
    return ` · dashed box = the live view ${Math.round(h.vieww)}×${Math.round(h.viewh)}`;
  };

  // ---------------------------------------------------------------- ghosts
  /* What the prediction says should exist at beat `i`: the player, every spawn
     fired so far, and the beacon currently waiting to be reached. Zones and
     scenery are deliberately out — the storm cells never move, and the nebula
     scatter is re-randomised on every entry, so comparing it would be noise. */
  function predicted(m, i) {
    const st = Core.stateAt(m, i);
    const out = [{ obj: m.player.object, x: m.player.x, y: m.player.y, what: 'player' }];
    st.spawns.forEach((sp) => out.push({ obj: sp.object, x: sp.x, y: sp.y, what: 'spawn' }));
    if (st.activeGate) out.push({ obj: 'MoveToArea', x: st.activeGate.x, y: st.activeGate.y, what: 'gate' });
    return out;
  }

  const DRIFT = 6;          // room units; below this a ghost is simply "on" its prediction

  L.overlay = function (ctx, tr, m, i) {
    if (L.mode !== 'ghosts' || !L.dump) return;
    const { X, Y, S } = tr;
    // Not a copy: nothing here mutates the dump, and this runs inside every
    // paintMap — which is every pointermove of a pan or a brush stroke.
    const ghosts = L.dump.instances;
    const preds = predicted(m, i);
    const used = new Set();

    // the game's real view rectangle, which is not the room's authored one
    const h = L.dump.head;
    if (h && h.vieww) {
      ctx.save();
      ctx.setLineDash([3, 5]);
      ctx.strokeStyle = 'rgba(127,216,255,0.5)';
      ctx.lineWidth = 1;
      ctx.strokeRect(X(h.viewx), Y(h.viewy), S(h.vieww), S(h.viewh));
      ctx.restore();
    }

    // match each prediction to the nearest live instance of the same object.
    // Compared squared, rooted once for the winner — the comparison does not
    // need the true distance and Math.hypot is the costly part of this loop.
    preds.forEach((p) => {
      let best = -1, best2 = Infinity;
      ghosts.forEach((g, k) => {
        if (used.has(k) || g.obj !== p.obj) return;
        const dx = g.x - p.x, dy = g.y - p.y, d2 = dx * dx + dy * dy;
        if (d2 < best2) { best2 = d2; best = k; }
      });
      const bestd = Math.sqrt(best2);
      const px = X(p.x), py = Y(p.y);
      if (best < 0) {
        // predicted, and the game does not have it — the interesting failure
        ctx.save();
        ctx.strokeStyle = 'rgba(255,90,77,0.95)';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([2, 3]);
        ctx.beginPath(); ctx.arc(px, py, Math.max(9, S(90)), 0, 6.284); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = 'rgba(255,90,77,0.95)';
        ctx.font = '9px ui-monospace, monospace'; ctx.textAlign = 'center';
        ctx.fillText('not in game', px, py + Math.max(9, S(90)) + 10);
        ctx.restore();
        return;
      }
      used.add(best);
      const g = ghosts[best], gx = X(g.x), gy = Y(g.y);
      ctx.save();
      ctx.strokeStyle = 'rgba(127,216,255,0.95)';
      ctx.fillStyle = 'rgba(127,216,255,0.95)';
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(gx, gy, 4, 0, 6.284); ctx.stroke();
      if (bestd > DRIFT) {
        ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(gx, gy); ctx.stroke();
        ctx.font = '9px ui-monospace, monospace'; ctx.textAlign = 'left';
        ctx.fillText(Math.round(bestd) + 'px', gx + 6, gy - 5);
      }
      ctx.restore();
    });

    // Live instances the prediction never claimed — meteors, wreckage, whatever
    // the mission's own code spawned. Marked, not judged.
    //
    // Anything sitting *on* something already matched is skipped: a ship is one
    // prediction but fourteen ShipSections and eight turrets in the dump, and a
    // cross on each would bury the two marks that mean something under a cloud
    // of correct ones.
    const PART2 = 90 * 90;
    ctx.save();
    ctx.strokeStyle = 'rgba(127,216,255,0.35)';
    ctx.lineWidth = 1;
    ghosts.forEach((g, k) => {
      if (used.has(k)) return;
      if (preds.some((p) => {
        const dx = g.x - p.x, dy = g.y - p.y;
        return dx * dx + dy * dy < PART2;
      })) return;
      const gx = X(g.x), gy = Y(g.y);
      ctx.beginPath();
      ctx.moveTo(gx - 3, gy); ctx.lineTo(gx + 3, gy);
      ctx.moveTo(gx, gy - 3); ctx.lineTo(gx, gy + 3);
      ctx.stroke();
    });
    ctx.restore();
  };

  return L;
})();
