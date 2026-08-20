/* The mission sheet — everything in the file that is not a beat.
 *
 * The rail is beat-scoped by design (select a block, edit its verbs) and the map
 * is the arrangement, so the mission's own header — its size, its name, where
 * the player starts, what the failure message says — had nowhere to live and was
 * YAML-only. That is a hole in an editor that claims to own the file: `room:` in
 * particular decides the size of the world every other coordinate is measured
 * against, and the map has been drawing it from the model all along without ever
 * letting you touch it.
 *
 * One rule here is not like the rest of the editor. Every other field applies on
 * `input`, keystroke by keystroke. The room's width and height apply on
 * *commit* — blur or Enter — because the storm mask is sized from them, and
 * typing "3000" over "800" passes through 3, 30 and 300 on the way. Refitting a
 * 60-column mask to one column and back would leave nothing to refit. So the
 * size is read once, when you are done saying it, and the crop it implies is
 * reported rather than done silently.
 */
window.MissionPanel = (function () {
  'use strict';

  const css = `
.ms { position:absolute; left:12px; top:12px; z-index:6; width:262px; background:rgba(8,13,14,.94);
      border:1px solid var(--rule); border-radius:2px; padding:8px 10px; display:none;
      font:10px/1.6 var(--mono); color:var(--ink-dim); max-height:calc(100% - 24px); overflow:auto; }
.ms.on { display:block; }
.ms h6 { margin:0 0 6px; font:9.5px/1 var(--mono); letter-spacing:.16em; text-transform:uppercase; color:var(--phos); }
.ms h7 { display:block; margin:9px 0 3px; font:9px/1 var(--mono); letter-spacing:.14em;
         text-transform:uppercase; color:#3f5a55; border-top:1px solid var(--rule-soft); padding-top:7px; }
.ms .r { display:grid; grid-template-columns:52px minmax(0,1fr); gap:4px 8px; align-items:center; margin-top:4px; }
.ms .r > span { font-size:9px; letter-spacing:.08em; text-transform:uppercase; color:#3f5a55; }
.ms .xy { display:flex; gap:5px; align-items:center; }
.ms .xy span { color:#3f5a55; }
.ms input, .ms textarea { font:10.5px/1.45 var(--mono); background:#070d0e; color:var(--ink); width:100%;
                          border:1px solid var(--rule); border-radius:2px; padding:2px 4px; }
.ms input:focus, .ms textarea:focus { outline:none; border-color:var(--phos); }
.ms input.commit { border-color:var(--rule); }
.ms input.commit:focus { border-color:var(--amber); }
.ms .hint { margin-top:8px; color:#3f5a55; line-height:1.5; }
.ms .hint b { color:var(--ink-dim); font-weight:400; }
.ms .dim { color:var(--ink-faint); }
`;

  const S = { on: false, refs: null };

  // Room bounds. The low end is where the map stops being a map — the view is
  // 1024x768 and a room under it does not scroll at all; the high end is a
  // guard against a typo'd extra zero, not a limit GM7 imposes.
  const MINDIM = 256, MAXDIM = 12000;

  const m = () => App.mission;

  // The same dotted-path grammar the rail edits beats with, rooted at the
  // mission instead — `room.width`, not `spawn.0.x`. One implementation.
  const read = (path) => Core.getPath(m(), path);
  const write = (path, v) => Core.setPath(m(), path, v);

  const painted = (mm) =>
    ((mm.storm && mm.storm.mask) || []).reduce((n, r) => n + (r.match(/[#@]/g) || []).length, 0);

  /* The meteor settings as the compiler will see them, without writing them
     down. A mission file need not carry the block and the sheet still has to
     show the numbers, but *opening* a panel must not edit the mission — filling
     the block in here would put a value in the YAML that the author never
     typed. The block is created when one of them is, in the input handler.

     One level deep, because `speed` is a block: a mission naming only
     `speed: {min: 3}` gets build.py's max, and a shallow merge would show that
     field blank and invite an author to type the value it already has. */
  const metOf = (mm) => {
    const out = Object.assign({}, Core.Meteors.DEFAULTS, mm.meteors || {});
    for (const k in Core.Meteors.DEFAULTS) {
      const d = Core.Meteors.DEFAULTS[k];
      if (d && typeof d === 'object') out[k] = Object.assign({}, d, out[k]);
    }
    return out;
  };

  /* How long an empty field takes to fill, which is the only thing `refill`
     decides. Worth printing because the useful range has a ceiling the two
     numbers hide: past the ~1 minute a rock survives, cap*interval no longer
     reaches the cap and the density silently becomes something less than it
     says. The room is 30 steps to the second. */
  const ramp = (met) =>
    `${met.cap * met.interval} frames ≈ ${Math.round(met.cap * met.interval / 30)}s`;

  /* Take the typed size. Clamped, rounded, and then the mask is squared up to
     the new grid on the spot — the alternative is a save that quietly drops the
     rows the room no longer has. */
  function commitRoom(f) {
    const mm = m(), axis = f.dataset.room;
    const raw = Number(f.value);
    if (!isFinite(raw)) return refresh();
    const v = Math.max(MINDIM, Math.min(MAXDIM, Math.round(raw)));
    if (v === mm.room[axis]) return refresh();
    Core.Model.begin(mm);
    const before = painted(mm);
    mm.room[axis] = v;
    if (mm.storm) Core.Storm.ensure(mm);
    const lost = before - painted(mm);
    if (v !== Math.round(raw)) App.toast(`room ${axis} clamped to ${v} (${MINDIM}–${MAXDIM})`, 'bad');
    else if (lost > 0) App.toast(`${lost} painted storm cell${lost > 1 ? 's' : ''} fell outside the room — ctrl-Z puts them back`, 'bad');
    App.change();            // and the paint with it
    refresh();
  }

  function html() {
    const mm = m();
    const met = metOf(mm);
    const reg = met.region || {};
    // Raw, not merged — see `d` below. The sheet has to be able to tell a value
    // the author wrote from one the compiler supplied.
    const sg = mm.surge || {};
    const row = (label, inner) => `<div class="r"><span>${label}</span><div>${inner}</div></div>`;
    const t = (p, v) => `<input data-f="${p}" value="${Core.esc(v == null ? '' : v)}">`;
    const n = (p, v, w) => `<input data-f="${p}" data-n value="${v == null ? '' : v}"${w ? ` style="max-width:${w}"` : ''}>`;
    // A number that may be absent. Everything else here reads blank as 0, which
    // is right for a count and wrong for a region corner: 0 is the left edge of
    // the room and *absent* is "wherever the room ends", and a field that could
    // not say the second would make three of the four corners unwritable.
    const o = (p, v) => `<input data-f="${p}" data-n data-o value="${v == null ? '' : v}" placeholder="room">`;
    /* A surge field, showing the compiler's default as a *placeholder* rather
       than as a value. Unlike a meteor field, every surge key already has a
       default that behaves, so there is nothing to gain by writing all eight
       into the file the moment one of them is touched — and something to lose:
       a mission that says `speed: 1.2` and nothing else is a mission whose
       author changed the speed, which is worth being able to read off the file.
       Blank therefore means "whatever build.py says", and clearing a field
       deletes the key (see `o` above for the same rule on a region corner). */
    const d = (p, v, dflt) => `<input data-f="${p}" data-n data-o value="${v == null ? '' : v}"`
      + ` placeholder="${dflt == null ? Core.Surge.DEFAULTS[p.slice(6)] : dflt}">`;
    return `<h6>mission sheet</h6>
      ${row('title', t('title', mm.title))}
      ${row('subtitle', t('subtitle', mm.subtitle))}
      <h7>room</h7>
      ${row('size', `<div class="xy"><input class="commit" data-room="width" value="${mm.room.width}">
        <span>×</span><input class="commit" data-room="height" value="${mm.room.height}"></div>`)}
      ${row('caption', t('room.caption', mm.room.caption))}
      <h7>player</h7>
      ${row('object', t('player.object', mm.player.object))}
      ${row('start', `<div class="xy">${n('player.x', mm.player.x)}${n('player.y', mm.player.y)}</div>`)}
      ${row('damage', n('player.damage', mm.player.damage, '70px'))}
      <h7>on failure</h7>
      <textarea data-f="fail.ship" rows="3">${Core.esc((mm.fail && mm.fail.ship) || '')}</textarea>
      <h7>scenery</h7>
      ${row('nebulae', n('scenery.nebula', (mm.scenery && mm.scenery.nebula) || 0, '70px'))}
      <h7>meteors</h7>
      ${row('density', n('meteors.cap', met.cap, '70px'))}
      ${row('refill', n('meteors.interval', met.interval, '70px'))}
      ${row('from', t('meteors.from', met.from))}
      ${row('spread', n('meteors.spread', met.spread, '70px'))}
      ${row('speed', `<div class="xy">${n('meteors.speed.min', met.speed.min)}
        ${n('meteors.speed.max', met.speed.max)}</div>`)}
      ${row('region from', `<div class="xy">${o('meteors.region.x1', reg.x1)}${o('meteors.region.y1', reg.y1)}</div>`)}
      ${row('region to', `<div class="xy">${o('meteors.region.x2', reg.x2)}${o('meteors.region.y2', reg.y2)}</div>`)}
      <h7>camera limit</h7>
      ${row('stops at', o('bounds.x2', mm.bounds && mm.bounds.x2))}
      <h7>storm wall</h7>
      ${row('lights', d('surge.back', sg.back))}
      ${row('speed', d('surge.speed', sg.speed))}
      ${row('gap', `<div class="xy">${d('surge.gap', sg.gap)}${d('surge.slack', sg.slack)}</div>`)}
      ${row('rush', d('surge.rush', sg.rush))}
      ${row('parks at', d('surge.stop', sg.stop, mm.room.width))}
      ${row('damage', d('surge.dmg', sg.dmg))}
      ${row('shield', d('surge.shield', sg.shield))}
      <div class="hint"><b>density</b> is the number of rocks alive at once — a rock lives
        until it leaves the room, so the field settles there and stays. <b>refill</b> is
        frames between spawns, and only decides how long an empty field takes to reach
        that number (<span data-ramp>${ramp(met)}</span>). Scale the two together to
        change the density at the same ramp.</div>
      <div class="hint"><b>from</b> is the screen edge the rocks come IN by —
        <b>right</b>, <b>top</b>, <b>bottom</b>, <b>left</b> — and the heading follows from
        it, fanned <b>spread</b> degrees about straight across. They are created just
        outside that edge of the live view, so they are never born on screen at any
        aspect or zoom.</div>
      <div class="hint"><b>region</b> is the stretch of room the field may fall in: blank
        is the room's own edge, and the field dries up on its own where the player looks
        past it. Along the drift it decides <i>whether</i> rocks come, not where they
        start — that is what keeps a spawn off-screen, and it is not yours to move.</div>
      <div class="hint"><b>camera limit</b> is how far right the view may look, clamped
        exactly as the room's own right edge clamps it — the ship may still fly past it,
        only the camera stops. Set it and the mission <i>starts</i> clamped; a beat then
        turns <b>bounds: off</b> to open it, which is what a reveal is. Blank is no limit.</div>
      <div class="hint">the <b>storm wall</b> is lit by a beat (<b>surge: on</b>) and made of
        the storm above — no mask, no wall. It appears <b>lights</b> units behind the ship
        wherever the ship is at that moment, closes at <b>speed</b> a step and never slower,
        and if it falls further behind than <b>gap</b> + <b>slack</b> it closes at
        <b>rush</b>× until it is back to <b>gap</b>. It stops for good at <b>parks at</b>
        — set that short of any beat the player cannot run from, because inside the wall
        is <b>damage</b> a section per step and a cutscene cannot dodge. <b>shield</b> is
        the bubble each beacon holds against it, and against rocks all mission.</div>
      <div class="hint">every storm-wall field is blank for the compiler's default, shown
        greyed in the box. Type one and only that one is written to the file.</div>
      <div class="hint">the room is the world; the view scrolls over it, 768 world units tall
        and as wide as the display's aspect makes it (1365 at 16:9, and more again zoomed out).
        <b>size</b> applies when you leave the field, not as you type — the storm mask is
        cut to fit it. <b>m</b> puts this away.</div>`;
  }

  /* Values only, and never into the field you are typing in. Called on every
     model change so a beacon drag or an undo shows up here too. */
  function refresh() {
    const el = S.refs && S.refs.root.querySelector('.ms');
    if (!el || !S.on) return;
    el.querySelectorAll('[data-f]').forEach((f) => {
      if (f === document.activeElement) return;
      // Same fallback html() used, or a mission with no `meteors:` block would
      // draw the defaults once and then be blanked by the first refresh. Read
      // through the path grammar rather than by key: `speed.min` and
      // `region.x2` are two levels down, and a key lookup would find neither.
      const p = f.dataset.f;
      const v = p.indexOf('meteors.') === 0
        ? Core.getPath(metOf(m()), p.slice(8)) : read(p);
      f.value = v == null ? '' : v;
    });
    const rp = el.querySelector('[data-ramp]');
    if (rp) rp.textContent = ramp(metOf(m()));
    el.querySelectorAll('[data-room]').forEach((f) => {
      if (f === document.activeElement) return;
      f.value = m().room[f.dataset.room];
    });
  }

  /* Rebuild the panel. It normally refuses to while you are typing in it — the
     caret is worth more than a redundant redraw — but a reload (a load, an undo,
     an apply) replaces the model wholesale, and then the DOM is simply wrong. */
  function render(force) {
    const el = S.refs.root.querySelector('.ms');
    if (!force && el.contains(document.activeElement)) return refresh();
    el.innerHTML = html();
  }

  function toggle(on) {
    S.on = on == null ? !S.on : !!on;
    const el = S.refs.root.querySelector('.ms');
    el.classList.toggle('on', S.on);
    if (S.on) render();
    return S.on;
  }

  function mount(refs) {
    S.refs = refs;
    const el = document.createElement('div');
    el.className = 'ms';
    refs.cv.parentElement.appendChild(el);

    // The map is a pointer surface (beacons, the storm brush); the panel is not
    // part of it and must not start a drag or a stroke underneath itself.
    el.addEventListener('pointerdown', (e) => e.stopPropagation());
    el.addEventListener('focusin', (e) => {
      if (e.target.matches('input:not(.commit),textarea')) Core.Model.begin(m());
    });

    el.addEventListener('input', (e) => {
      const p = e.target.dataset.f;
      if (!p) return;
      let v = e.target.value;
      // Blank in an optional field is the absence of a value, not zero — see the
      // `o` field above. undefined is what setPath deletes with.
      if (e.target.dataset.o != null && v.trim() === '') v = undefined;
      else if (e.target.dataset.n != null) {
        const num = Number(v);
        if (!isFinite(num)) return;
        v = num;
      }
      // Typing one of these is what creates the block, and it has to arrive
      // whole: setPath would write `meteors: {cap: 48}` and the YAML writer
      // prints every key, so the rest would go out as `undefined`.
      if (p.indexOf('meteors.') === 0) Core.Meteors.ensure(m());
      write(p, v);
      App.change();          // the inspector's 'change' subscriber does the paint
    });

    // Size commits on blur or Enter — see the note at the top of the file.
    el.addEventListener('change', (e) => { if (e.target.dataset.room) commitRoom(e.target); });
    el.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && e.target.dataset.room) e.target.blur();
      if (e.key === 'Escape') { e.target.blur(); toggle(false); }
    });

    App.on('fields', refresh);
    App.on('reload', () => { if (S.on) render(true); });
  }

  function key(e) {
    if (e.key === 'm') { toggle(); return true; }
    return false;
  }

  return { css, mount, toggle, key, render, state: S };
})();
