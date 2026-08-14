/* PROTOTYPE — shared model + prediction renderer for the mission-editor variants.
 *
 * Nothing here is layout. Layout is what the four variants disagree about; this
 * file is the stuff they all need to agree on:
 *   - beat numbering, identical to build.py's number_beats()
 *   - the action vocabulary of one beat (tier-2 verbs) and its geometry
 *   - cumulative mission state at beat N (for scrubbing)
 *   - the canvas "predicted view" renderer
 *   - a YAML-subset parser (variant D edits source text live)
 *   - a ladder emitter that mirrors build.py's Emitter, so the compiled GML is
 *     visible in the editor
 *   - the lint checks build.py enforces
 */
window.Core = (function () {
  'use strict';

  // ---------------------------------------------------------------- helpers
  const onoff = (v) => (v === true ? 'on' : v === false ? 'off' : v);
  const SAY_COLOR = { green: '--phos', red: '--hostile', magenta: '--alien', white: '--log' };
  const sayClass = (s) => ({ red: 'foe', magenta: 'alien', white: 'log' }[(s && s.color) || 'green'] || 'hq');
  const brk = (s) => String(s == null ? '' : s).split('#').map((p) => p.trim()).filter(Boolean);

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6d2b79f5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // ------------------------------------------------- beat numbering (build.py)
  // Beat 0 runs from alarm[2] with the counter still 0. Every later beat claims
  // the next rung; `wait: gate` reserves one extra slot so the MoveToArea's own
  // +1 lands on the following beat whatever the message timing was.
  function numberBeats(m) {
    const out = [{ n: 'start', rung: 0, i: 0, beat: m.beats[0] }];
    let n = 1;
    for (let i = 1; i < m.beats.length; i++) {
      const b = m.beats[i];
      out.push({ n: n, rung: n, i: i, beat: b });
      n += 1;
      if (b.wait === 'gate') n += 1;
    }
    return out;
  }

  // What moves the counter off this beat — drawn on the connector, not the card.
  function advanceOf(b) {
    if (!b) return null;
    if (b.win) return { kind: 'end', label: 'mission accomplished' };
    if (b.wait === 'gate') return { kind: 'gate', label: 'ship reaches the gate', sub: 'MoveToArea +1 · slot reserved' };
    if (b.say || b.objective != null) return { kind: 'message', label: 'message panel closed', sub: 'GUI_Messager destroy +1' };
    return { kind: 'auto', label: 'immediately', sub: 'sets counter, re-fires event_user(0)' };
  }

  // ---------------------------------------------- one beat -> action vocabulary
  // Order mirrors build.py's Emitter.actions() so the cards read like the GML.
  function actionsOf(b, m) {
    const A = [];
    const push = (k, icon, label, detail, geo) => A.push({ k, icon, label, detail, geo });
    if (b.music === 'stop') push('music', '♫', 'music', 'stop');
    else if (b.music) push('music', '♫', 'music', String(b.music));
    if (onoff(b.eerie) === 'on') push('eerie', '◌', 'ambience', 'snd_eeriesound loop');
    else if (onoff(b.eerie) === 'off') push('eerie', '◌', 'ambience', 'stop eerie');
    if (b.autosave) push('autosave', '◉', 'autosave', 'unless difficulty = Hard');
    if (b.camera) push('camera', '▣', 'camera', `(${b.camera.x}, ${b.camera.y}) speed ${b.camera.speed == null ? 60 : b.camera.speed}`,
      { type: 'camera', x: b.camera.x, y: b.camera.y });
    (b.spawn || []).forEach((sp) => push('spawn', '◆', 'spawn', `${sp.object} at (${sp.x}, ${sp.y})${sp.name ? ' as ' + sp.name : ''}`,
      { type: 'spawn', x: sp.x, y: sp.y, label: sp.object }));
    if (b.ping) push('ping', '◎', 'ping', `(${b.ping[0]}, ${b.ping[1]})`, { type: 'ping', x: b.ping[0], y: b.ping[1] });
    if (onoff(b.meteors) === 'on') push('meteors', '✦', 'meteors', 'spawner on');
    else if (onoff(b.meteors) === 'off') push('meteors', '✦', 'meteors', 'spawner off');
    if (b.objective != null) push('objective', '▶', 'objective', b.objective);
    if (b.say) push('say', '▰', 'say', b.say.who);
    if (b.gate != null && m.gates[b.gate]) push('gate', '◇', 'gate', `beacon ${b.gate + 1} (${m.gates[b.gate].x}, ${m.gates[b.gate].y})`,
      { type: 'gate', x: m.gates[b.gate].x, y: m.gates[b.gate].y, idx: b.gate });
    if (b.gate_at) push('gate', '◇', 'gate', `ad-hoc (${b.gate_at.x}, ${b.gate_at.y})`,
      { type: 'gate', x: b.gate_at.x, y: b.gate_at.y, idx: -1 });
    if (b.win) push('win', '★', 'win', 'missionSucc()');
    (b.exec || []).forEach((raw) => push('exec', '⌘', 'gml', raw));
    return A;
  }

  const geoOf = (b, m) => actionsOf(b, m).map((a) => a.geo).filter(Boolean);

  // ------------------------------------------ cumulative state at beat i
  function stateAt(m, upTo) {
    const st = {
      spawns: [], gatesDone: [], activeGate: null, meteors: false,
      music: null, eerie: false, camera: { x: m.player.x, y: m.player.y },
      objective: null, say: null, saves: 0, won: false,
    };
    for (let i = 0; i <= Math.min(upTo, m.beats.length - 1); i++) {
      const b = m.beats[i];
      if (b.music) st.music = b.music;
      if (onoff(b.eerie) === 'on') st.eerie = true;
      if (onoff(b.eerie) === 'off') st.eerie = false;
      if (onoff(b.meteors) === 'on') st.meteors = true;
      if (onoff(b.meteors) === 'off') st.meteors = false;
      if (b.autosave) st.saves++;
      if (b.camera) st.camera = { x: b.camera.x, y: b.camera.y };
      (b.spawn || []).forEach((sp) => st.spawns.push(sp));
      if (b.objective != null) st.objective = b.objective;
      if (b.say) st.say = b.say;
      if (st.activeGate) { st.gatesDone.push(st.activeGate); st.activeGate = null; }
      if (b.gate != null && m.gates[b.gate]) st.activeGate = { x: m.gates[b.gate].x, y: m.gates[b.gate].y, idx: b.gate };
      if (b.gate_at) st.activeGate = { x: b.gate_at.x, y: b.gate_at.y, idx: -1 };
      if (b.win) st.won = true;
    }
    return st;
  }

  // Things with no position in the sequence — the "always watching" panel.
  function alwaysOn(m) {
    const out = [{
      k: 'fail', title: 'ship lost', when: 'Step, every frame',
      detail: 'if the player ship stops existing: centre camera on the last event, missionFail(...)',
      text: m.fail && m.fail.ship,
    }];
    if (m.zones && m.zones.length) out.push({
      k: 'zones', title: `${m.zones.length} storm cells`, when: 'zone object Step',
      detail: 'every ShipSection owned by the player inside the radius loses l_dmg HP per step',
      text: m.zones.map((z) => `(${z.x}, ${z.y}) r${z.r} −${z.dmg}hp`).join('   '),
    });
    if (m.meteors) out.push({
      k: 'meteors', title: 'meteor spawner', when: `alarm[5], every ${m.meteors.interval} frames`,
      detail: `while on and fewer than ${m.meteors.cap} live obs_Meteor, drift one in from the right of the ship`,
      text: 'toggled by beats — on at beat 3, off at beat 10',
    });
    return out;
  }

  // ---------------------------------------------------------------- the lint
  // Same rules build.py enforces; the editor should never let you author past them.
  const BEAT_KEYS = ['start', 'say', 'objective', 'gate', 'gate_at', 'wait', 'autosave',
    'music', 'eerie', 'meteors', 'camera', 'spawn', 'ping', 'win', 'exec'];

  function lint(m) {
    const errs = [];
    const text = (s, where) => {
      if (s == null) return;
      if (String(s).indexOf('"') >= 0) errs.push({ where, msg: 'double quote in text (GM7 has no escapes)' });
      for (const ch of '—–’‘“”…')
        if (String(s).indexOf(ch) >= 0) errs.push({ where, msg: `non-ASCII '${ch}' (game font has no glyph)` });
    };
    if (!m.beats[0] || !m.beats[0].start) errs.push({ where: 'beat 0', msg: 'first beat must have start: true' });
    m.beats.forEach((b, i) => {
      const where = `beat ${i}`;
      Object.keys(b).forEach((k) => {
        if (BEAT_KEYS.indexOf(k) < 0) errs.push({ where, msg: `unknown beat key '${k}'` });
      });
      if ((b.say ? 1 : 0) + (b.objective != null ? 1 : 0) > 1)
        errs.push({ where, msg: 'more than one message panel in a beat' });
      if (b.say) { text(b.say.who, where); text(b.say.text, where); }
      if (b.objective != null) text(b.objective, where);
      if (b.gate != null && !m.gates[b.gate]) errs.push({ where, msg: `gate ${b.gate} does not exist` });
      if (b.music && ['stop', 'theme', 'battle'].indexOf(b.music) < 0)
        errs.push({ where, msg: 'music must be stop | theme | battle' });
    });
    if (m.fail) text(m.fail.ship, 'fail.ship');
    return errs;
  }

  // ------------------------------------------------- GML the compiler will emit
  const COLORS = { green: '$00FF00', red: 'c_red', magenta: '$FF00FF', white: 'c_white' };

  function beatStmts(b, m, g, tvar) {
    const out = [];
    if (b.music === 'stop') out.push('stopMusic()');
    else if (b.music === 'theme') out.push('stopMusic(); bgm_Play(global.mus_theme,1)');
    else if (b.music === 'battle') out.push('stopMusic(); bgm_Play(global.mus_battle,1)');
    if (onoff(b.eerie) === 'on') out.push('sound_loop(snd_eeriesound)');
    else if (onoff(b.eerie) === 'off') out.push('sound_stop(snd_eeriesound)');
    if (b.autosave) out.push('if (global.difficulty != World_Hard) saveGame()');
    if (b.camera) {
      out.push(`centreCamera(${b.camera.x},${b.camera.y},${b.camera.speed == null ? 60 : b.camera.speed})`);
      out.push(`global.lasteventx = ${b.camera.x}; global.lasteventy = ${b.camera.y}`);
    }
    (b.spawn || []).forEach((sp) => out.push(sp.name
      ? `global.${g}_${sp.name} = instance_create(${sp.x},${sp.y},${sp.object})`
      : `instance_create(${sp.x},${sp.y},${sp.object})`));
    if (b.ping) out.push(`showPing(${b.ping[0]},${b.ping[1]})`);
    if (onoff(b.meteors) === 'on') out.push(`global.${g}_meteors = 1; alarm[5] = 1`);
    else if (onoff(b.meteors) === 'off') out.push(`global.${g}_meteors = 0`);
    if (b.objective != null) out.push(`showMessage(0,c_red,"New Objective",${tvar(b.objective)},spr_MesObj)`);
    if (b.say) {
      const s = b.say;
      const who = s.who.indexOf("'") >= 0 ? tvar(s.who) : `"${s.who}"`;
      out.push(`showMessage(${s.delay || 0},${COLORS[s.color || 'green']},${who},${tvar(s.text)},${s.sprite || 'spr_MesHint'})`);
    }
    const gate = (x, y) => out.push(`g = instance_create(${x},${y},MoveToArea); g.l_target = global.${g}_ship; showPing(${x},${y})`);
    if (b.gate != null && m.gates[b.gate]) gate(m.gates[b.gate].x, m.gates[b.gate].y);
    if (b.gate_at) gate(b.gate_at.x, b.gate_at.y);
    if (b.win) out.push(`global.${g}_won = 1; missionSucc()`);
    (b.exec || []).forEach((raw) => out.push(raw));
    return out;
  }

  // The whole User Event 0 ladder, the way build.py writes it.
  function emitLadder(m) {
    const g = m.id;
    let tn = 0;
    const texts = [];
    const tvar = (s) => { const nm = `global.${g}_t${tn++}`; texts.push([nm, s]); return nm; };
    const numbered = numberBeats(m);
    // the start beat is emitted into alarm[2], not the ladder — number its texts first
    const startStmts = beatStmts(m.beats[0], m, g, tvar);
    const rungs = numbered.slice(1).map(({ n, beat }) => {
      const stmts = beatStmts(beat, m, g, tvar);
      const hasMsg = !!beat.say || beat.objective != null;
      if (!hasMsg && !beat.win) stmts.push(`l_messagecount = ${n + 1}; event_user(0)`);
      return { n, body: stmts };
    });
    return { texts, startStmts, rungs };
  }

  function ladderText(m) {
    const { texts, startStmts, rungs } = emitLadder(m);
    const L = [];
    L.push('// ------ dialogue globals (plain file scope, apostrophes legal here)');
    texts.slice(0, 3).forEach(([n, s]) => L.push(`${n} = "${String(s).slice(0, 58)}${String(s).length > 58 ? '…' : ''}";`));
    L.push(`// … ${texts.length} strings total`);
    L.push('');
    L.push('// ------ alarm[2]: the opening beat, counter still 0');
    startStmts.forEach((s) => L.push(s + ';'));
    L.push('');
    L.push('// ------ user event 0 (7:10): the whole campaign script');
    L.push('var g;');
    rungs.forEach((r, i) => {
      L.push(`${i ? 'else ' : ''}if (l_messagecount = ${r.n}) {`);
      r.body.forEach((s) => L.push('  ' + s + ';'));
      L.push('}');
    });
    return L.join('\n');
  }

  // ------------------------------------------------------ prediction renderer
  // The canvas view every variant shows — sized and framed differently by each.
  function drawMap(canvas, o) {
    const m = o.mission, ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.clientWidth, H = canvas.clientHeight;
    if (!W || !H) return null;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const pad = o.pad == null ? 18 : o.pad;
    const k = Math.min((W - pad * 2) / m.room.width, (H - pad * 2) / m.room.height) * (o.zoom || 1);
    let ox = (W - m.room.width * k) / 2, oy = (H - m.room.height * k) / 2;
    if (o.center) { ox = W / 2 - o.center.x * k; oy = H / 2 - o.center.y * k; }
    const X = (x) => ox + x * k, Y = (y) => oy + y * k, S = (r) => r * k;
    const css = getComputedStyle(document.documentElement);
    const c = (n) => css.getPropertyValue(n).trim();
    const st = o.reveal == null ? null : stateAt(m, o.reveal);
    const focus = o.focus || null;
    const fkeys = focus ? geoOf(focus, m).map((gg) => `${gg.type}:${gg.x}:${gg.y}`) : [];
    const lit = (gg) => !focus || fkeys.indexOf(`${gg.type}:${gg.x}:${gg.y}`) >= 0;

    // Game art is drawn in world units under a scaled transform, so sprite
    // origins and sizes are the game's numbers, not screen guesses.
    const art = window.Assets && window.Assets.ok && o.art !== false ? window.Assets : null;
    const world = (fn) => {
      ctx.save(); ctx.translate(ox, oy); ctx.scale(k, k); fn(); ctx.restore();
    };

    ctx.fillStyle = '#04070a'; ctx.fillRect(0, 0, W, H);
    // room + grid
    ctx.save();
    ctx.beginPath(); ctx.rect(X(0), Y(0), S(m.room.width), S(m.room.height)); ctx.clip();
    // the mission rooms are black with all eight background slots unused — the
    // starfield is procedural, so the prediction draws one too
    const srnd = mulberry32(99);
    for (let i = 0; i < 220; i++) {
      const sx = X(srnd() * m.room.width), sy = Y(srnd() * m.room.height), a = 0.10 + srnd() * 0.35;
      ctx.fillStyle = `rgba(200,225,255,${a})`;
      ctx.fillRect(sx, sy, 1, 1);
    }
    ctx.strokeStyle = 'rgba(120,180,160,0.055)'; ctx.lineWidth = 1;
    for (let gx = 0; gx <= m.room.width; gx += 500) { ctx.beginPath(); ctx.moveTo(X(gx), Y(0)); ctx.lineTo(X(gx), Y(m.room.height)); ctx.stroke(); }
    for (let gy = 0; gy <= m.room.height; gy += 500) { ctx.beginPath(); ctx.moveTo(X(0), Y(gy)); ctx.lineTo(X(m.room.width), Y(gy)); ctx.stroke(); }
    // scenery: `nebula: N` scatters at create — seeded so it stays put between
    // redraws, which is a prediction: the game re-randomises every run
    const rnd = mulberry32(1337);
    const neb = (m.scenery && m.scenery.nebula) || 0;
    for (let i = 0; i < neb; i++) {
      const wx = rnd() * m.room.width, wy = rnd() * m.room.height, jitter = 0.8 + rnd() * 0.7;
      if (art && art.spriteOf('ter_Nebula')) {
        world(() => art.drawObject(ctx, 'ter_Nebula', wx, wy, { scale: jitter }));
      } else {
        const nr = S(120 + jitter * 120);
        const grd = ctx.createRadialGradient(X(wx), Y(wy), 0, X(wx), Y(wy), nr);
        grd.addColorStop(0, 'rgba(70,110,150,0.16)'); grd.addColorStop(1, 'rgba(70,110,150,0)');
        ctx.fillStyle = grd; ctx.beginPath(); ctx.arc(X(wx), Y(wy), nr, 0, 6.284); ctx.fill();
      }
    }
    ctx.restore();
    ctx.strokeStyle = c('--rule'); ctx.lineWidth = 1; ctx.strokeRect(X(0), Y(0), S(m.room.width), S(m.room.height));

    // storm cells
    (m.zones || []).forEach((z) => {
      ctx.beginPath(); ctx.arc(X(z.x), Y(z.y), S(z.r), 0, 6.284);
      ctx.fillStyle = 'rgba(255,60,50,0.10)'; ctx.fill();
      ctx.strokeStyle = 'rgba(255,90,77,0.45)'; ctx.lineWidth = 1.5; ctx.stroke();
    });

    // the route — player start through the gates in order
    const pts = [[m.player.x, m.player.y]].concat((m.gates || []).map((g2) => [g2.x, g2.y]));
    m.beats.forEach((b) => { if (b.gate_at) pts.push([b.gate_at.x, b.gate_at.y]); });
    if (o.route !== false) {
      ctx.save(); ctx.setLineDash([6, 6]); ctx.strokeStyle = 'rgba(78,240,138,0.35)'; ctx.lineWidth = 1.5;
      ctx.beginPath(); pts.forEach((p, i) => (i ? ctx.lineTo(X(p[0]), Y(p[1])) : ctx.moveTo(X(p[0]), Y(p[1])))); ctx.stroke(); ctx.restore();
    }

    // gates — the real MoveToArea marker (spr_Marker, image_blend = c_green),
    // plus the editor's own ring so an unreached beacon is still findable
    (m.gates || []).forEach((g2, i) => {
      const done = st && st.gatesDone.some((d) => d.idx === i);
      const active = st && st.activeGate && st.activeGate.idx === i;
      const on = lit({ type: 'gate', x: g2.x, y: g2.y });
      if (art) world(() => art.drawObject(ctx, 'MoveToArea', g2.x, g2.y,
        { frame: active ? 0 : 6, alpha: done ? 0.35 : on ? 1 : 0.4, scale: 2 }));
      ctx.beginPath(); ctx.arc(X(g2.x), Y(g2.y), Math.max(5, S(70)), 0, 6.284);
      ctx.strokeStyle = active ? c('--phos-hot') : done ? 'rgba(78,240,138,0.85)' : on ? 'rgba(78,240,138,0.5)' : 'rgba(78,240,138,0.18)';
      ctx.lineWidth = active ? 2.5 : 1.5; ctx.stroke();
      if (done) { ctx.fillStyle = 'rgba(78,240,138,0.30)'; ctx.fill(); }
      if (o.labels !== false) {
        ctx.fillStyle = on ? c('--ink-dim') : 'rgba(139,156,149,0.3)';
        ctx.font = '10px ui-monospace, monospace'; ctx.textAlign = 'center';
        ctx.fillText(String(i + 1), X(g2.x), Y(g2.y) - Math.max(9, S(70)) - 4);
      }
    });

    // scripted spawns (all of them, or only those already fired when scrubbing)
    const spawns = [];
    m.beats.forEach((b, bi) => (b.spawn || []).forEach((sp) => spawns.push({ sp, bi })));
    // an object as the game would draw it: a real hull if the render-model dump
    // has one, else the object's own sprite with its own blend
    function drawActor(obj, wx, wy, alpha, team) {
      if (!art) return false;
      const hull = art.ship(obj);
      if (hull) {
        let ok = false;
        world(() => { ctx.globalAlpha = alpha; ok = art.drawShip(ctx, hull, wx, wy, { team: team || 0 }); ctx.globalAlpha = 1; });
        if (ok) return true;
      }
      let drew = false;
      world(() => { drew = art.drawObject(ctx, obj, wx, wy, { alpha }); });
      return drew;
    }

    spawns.forEach(({ sp, bi }) => {
      const shown = st ? bi <= o.reveal : true;
      const on = lit({ type: 'spawn', x: sp.x, y: sp.y });
      const alpha = shown ? (on ? 1 : 0.5) : 0.18;
      const real = drawActor(sp.object, sp.x, sp.y, alpha, /ally|Allied|Space|Hestia/.test(sp.object) ? 1 : 2);
      ctx.globalAlpha = shown ? (on ? 1 : 0.28) : 0.13;
      ctx.strokeStyle = c('--alien'); ctx.lineWidth = 1.5;
      const s2 = Math.max(5, S(60));
      if (real) {                       // a corner bracket, so art stays readable
        const b = s2 * 0.55, L = s2 * 0.4;
        [[-1, -1], [1, -1], [-1, 1], [1, 1]].forEach(([sx, sy]) => {
          ctx.beginPath();
          ctx.moveTo(X(sp.x) + sx * b, Y(sp.y) + sy * b - sy * L);
          ctx.lineTo(X(sp.x) + sx * b, Y(sp.y) + sy * b);
          ctx.lineTo(X(sp.x) + sx * b - sx * L, Y(sp.y) + sy * b);
          ctx.stroke();
        });
      } else ctx.strokeRect(X(sp.x) - s2, Y(sp.y) - s2, s2 * 2, s2 * 2);
      if (o.labels !== false) {
        ctx.fillStyle = c('--alien'); ctx.font = '10px ui-monospace, monospace'; ctx.textAlign = 'center';
        ctx.fillText(sp.object, X(sp.x), Y(sp.y) - s2 - 5);
      }
      ctx.globalAlpha = 1;
    });

    // player start
    const px = X(m.player.x), py = Y(m.player.y);
    if (!drawActor(m.player.object, m.player.x, m.player.y, 1, 0)) {
      ctx.fillStyle = c('--phos');
      ctx.beginPath(); ctx.moveTo(px + 8, py); ctx.lineTo(px - 6, py - 6); ctx.lineTo(px - 6, py + 6); ctx.closePath(); ctx.fill();
    }
    if (o.labels !== false) {
      ctx.fillStyle = c('--phos');
      ctx.font = '9px ui-monospace, monospace'; ctx.textAlign = 'center';
      ctx.fillText(m.player.object.toUpperCase(), px, py - Math.max(14, S(70)));
    }

    // camera frame — the game's view is 1024x768
    if (o.camera !== false) {
      const cam = st ? st.camera : (focus && focus.camera) || null;
      if (cam) {
        ctx.save(); ctx.setLineDash([4, 4]); ctx.strokeStyle = 'rgba(198,211,205,0.45)'; ctx.lineWidth = 1;
        ctx.strokeRect(X(cam.x - 512), Y(cam.y - 384), S(1024), S(768)); ctx.restore();
      }
    }

    // focused beat's own geometry, on top
    if (focus) {
      geoOf(focus, m).forEach((gg) => {
        ctx.beginPath(); ctx.arc(X(gg.x), Y(gg.y), Math.max(10, S(110)), 0, 6.284);
        ctx.strokeStyle = c('--phos-hot'); ctx.lineWidth = 1; ctx.globalAlpha = 0.8; ctx.stroke(); ctx.globalAlpha = 1;
      });
    }
    return { X, Y, S, k, ox, oy };
  }

  // --------------------------------------------------------- YAML (subset)
  // Enough of YAML for the mission DSL: block maps, block seqs, flow maps/seqs,
  // quoted + plain scalars, comments. Variant D parses the textarea with this.
  function parseYaml(text) {
    const lines = [];
    text.split(/\r?\n/).forEach((raw, i) => {
      const s = stripComment(raw);
      if (!s.trim()) return;
      lines.push({ indent: s.match(/^ */)[0].length, text: s.trim(), no: i + 1 });
    });
    let p = 0;
    function parseBlock(indent) {
      if (p >= lines.length) return null;
      if (lines[p].text[0] === '-' && lines[p].indent >= indent) return parseSeq(lines[p].indent);
      return parseMap(indent);
    }
    function parseMap(indent) {
      const obj = {};
      while (p < lines.length && lines[p].indent >= indent) {
        if (lines[p].indent > indent) throw new Error(`line ${lines[p].no}: unexpected indent`);
        const ln = lines[p];
        const mm = ln.text.match(/^([^:]+):\s*(.*)$/);
        if (!mm) throw new Error(`line ${ln.no}: expected 'key: value'`);
        const key = mm[1].trim(), rest = mm[2].trim();
        p++;
        if (rest) obj[key] = scalar(rest, ln.no);
        else if (p < lines.length && lines[p].indent > indent) obj[key] = parseBlock(lines[p].indent);
        else if (p < lines.length && lines[p].indent === indent && lines[p].text[0] === '-') obj[key] = parseSeq(indent);
        else obj[key] = null;
      }
      return obj;
    }
    function parseSeq(indent) {
      const arr = [];
      while (p < lines.length && lines[p].indent === indent && lines[p].text[0] === '-') {
        const ln = lines[p];
        const rest = ln.text.slice(1).trim();
        p++;
        if (!rest) { arr.push(p < lines.length && lines[p].indent > indent ? parseBlock(lines[p].indent) : null); continue; }
        if (/^[^:{[]+:/.test(rest)) {
          // `- key: value` opens a map whose remaining keys sit at the key column;
          // put the key back as a synthetic line and let parseMap take it.
          const col = ln.indent + (ln.text.length - rest.length);
          lines.splice(p, 0, { indent: col, text: rest, no: ln.no });
          arr.push(parseMap(col));
        } else arr.push(scalar(rest, ln.no));
      }
      return arr;
    }
    function scalar(s, no) {
      if (s[0] === '{' || s[0] === '[') return JSON.parse(flowToJson(s, no));
      if (s[0] === '"' || s[0] === "'") return s.slice(1, -1);
      if (/^-?\d+$/.test(s)) return parseInt(s, 10);
      if (/^-?\d*\.\d+$/.test(s)) return parseFloat(s);
      if (/^(true|yes)$/i.test(s)) return true;
      if (/^(false|no)$/i.test(s)) return false;
      if (/^on$/i.test(s)) return true;      // YAML 1.1, same as PyYAML
      if (/^off$/i.test(s)) return false;
      if (/^(null|~)$/i.test(s)) return null;
      return s;
    }
    function flowToJson(s, no) {
      let out = '', i = 0;
      while (i < s.length) {
        const ch = s[i];
        if (ch === '"' || ch === "'") {
          let j = i + 1; while (j < s.length && s[j] !== ch) j++;
          out += JSON.stringify(s.slice(i + 1, j)); i = j + 1; continue;
        }
        if (/[\w.\-+]/.test(ch)) {
          let j = i; while (j < s.length && /[\w.\-+ ]/.test(s[j])) j++;
          let tok = s.slice(i, j).trim(); i = j;
          const after = s.slice(i).match(/^\s*:/);
          if (after) out += JSON.stringify(tok);
          else if (/^-?\d+(\.\d+)?$/.test(tok)) out += tok;
          else if (/^(true|on|yes)$/i.test(tok)) out += 'true';
          else if (/^(false|off|no)$/i.test(tok)) out += 'false';
          else out += JSON.stringify(tok);
          continue;
        }
        out += ch; i++;
      }
      if (!/^[[{]/.test(out)) throw new Error(`line ${no}: bad flow value`);
      return out;
    }
    function stripComment(s) {
      let q = null;
      for (let i = 0; i < s.length; i++) {
        const ch = s[i];
        if (q) { if (ch === q) q = null; continue; }
        if (ch === '"' || ch === "'") { q = ch; continue; }
        if (ch === '#' && (i === 0 || /\s/.test(s[i - 1]))) return s.slice(0, i).replace(/\s+$/, '');
      }
      return s.replace(/\s+$/, '');
    }
    const doc = parseBlock(0);
    return doc;
  }

  // ------------------------------------------------------------ YAML out
  // The editor's edits have to come back out as the DSL or none of this counts.
  // Style follows missions/ep9.yaml: block maps, flow maps for coordinates.
  function toYaml(m) {
    const q = (s) => `"${String(s)}"`;
    const qw = (s) => (/^[A-Za-z][A-Za-z0-9 ._-]*$/.test(s) ? s : q(s));
    const flow = (o, keys) => '{' + keys.filter((k) => o[k] != null).map((k) => `${k}: ${o[k]}`).join(', ') + '}';
    const L = [];
    L.push(`id: ${m.id}`, `episode: ${m.episode}`, `mission: ${m.mission}`,
      `title: ${m.title}`, `subtitle: ${m.subtitle}`, '');
    L.push('room:', `  width: ${m.room.width}`, `  height: ${m.room.height}`,
      `  caption: ${m.room.caption}`, '');
    L.push('player:', `  object: ${m.player.object}`, `  x: ${m.player.x}`, `  y: ${m.player.y}`,
      `  damage: ${m.player.damage}`, '');
    L.push('fail:', `  ship: ${q(m.fail.ship)}`, '');
    if (m.scenery) L.push('scenery:', `  nebula: ${m.scenery.nebula}`, '');
    if (m.zones) { L.push('zones:'); m.zones.forEach((z) => L.push('  - ' + flow(z, ['x', 'y', 'r', 'dmg']))); L.push(''); }
    if (m.gates) { L.push('gates:'); m.gates.forEach((g) => L.push('  - ' + flow(g, ['x', 'y']))); L.push(''); }
    if (m.meteors) L.push('meteors:', `  interval: ${m.meteors.interval}`, `  cap: ${m.meteors.cap}`, '');
    L.push('beats:');
    const ORDER = ['start', 'music', 'eerie', 'meteors', 'autosave', 'camera', 'spawn',
      'ping', 'objective', 'say', 'gate', 'gate_at', 'wait', 'win', 'exec'];
    m.beats.forEach((b) => {
      const rows = [];
      ORDER.forEach((k) => {
        if (!(k in b)) return;
        const v = b[k];
        if (k === 'say') {
          rows.push('say:', `  who: ${qw(v.who)}`, `  sprite: ${v.sprite || 'spr_MesHint'}`);
          if (v.color) rows.push(`  color: ${v.color}`);
          rows.push(`  text: ${q(v.text)}`);
        } else if (k === 'spawn') {
          rows.push('spawn:');
          v.forEach((sp) => rows.push('  - ' + flow(sp, ['object', 'x', 'y', 'name'])));
        } else if (k === 'camera') rows.push(`camera: ${flow(v, ['x', 'y', 'speed'])}`);
        else if (k === 'gate_at') rows.push(`gate_at: ${flow(v, ['x', 'y'])}`);
        else if (k === 'ping') rows.push(`ping: [${v[0]}, ${v[1]}]`);
        else if (k === 'objective') rows.push(`objective: ${q(v)}`);
        else if (k === 'eerie' || k === 'meteors') rows.push(`${k}: ${v === true ? 'on' : v === false ? 'off' : v}`);
        else if (k === 'exec') { rows.push('exec:'); v.forEach((e) => rows.push(`  - ${q(e)}`)); }
        else rows.push(`${k}: ${v}`);
      });
      rows.forEach((r, i) => L.push((i ? '    ' : '  - ') + r));
      L.push('');
    });
    return L.join('\n');
  }

  // ------------------------------------------------------- editing the model
  // Structural edits shared by every editing variant. They mutate in place —
  // App.mission is held by reference everywhere — and snapshot for undo first.
  const Model = (function () {
    const past = [];
    const snap = (m) => { past.push(JSON.stringify(m)); if (past.length > 80) past.shift(); };
    const restore = (m, json) => {
      const o = JSON.parse(json);
      Object.keys(m).forEach((k) => delete m[k]);
      Object.assign(m, o);
    };
    const lastSay = (m, at) => {
      for (let i = Math.min(at, m.beats.length) - 1; i >= 0; i--) if (m.beats[i].say) return m.beats[i].say;
      return { who: 'Helm', sprite: 'spr_MesMan1' };
    };
    const TEMPLATES = {
      say: (m, at) => ({ say: { who: lastSay(m, at).who, sprite: lastSay(m, at).sprite, text: 'New line of dialogue.' } }),
      objective: () => ({ objective: 'New objective' }),
      spawn: (m) => ({ spawn: [{ object: 'EPirate06', x: Math.round(m.room.width / 2), y: Math.round(m.room.height / 2) }] }),
      gate: (m) => ({ gate: 0, wait: 'gate' }),
      camera: (m) => ({ camera: { x: Math.round(m.room.width / 2), y: Math.round(m.room.height / 2), speed: 60 } }),
      meteors: () => ({ meteors: true }),
      music: () => ({ music: 'theme' }),
      autosave: () => ({ autosave: true }),
      win: () => ({ win: true }),
      empty: () => ({}),
    };
    return {
      canUndo: () => past.length > 0,
      undo(m) { if (past.length) restore(m, past.pop()); },
      insert(m, at, kind) {
        snap(m);
        at = Math.max(1, Math.min(m.beats.length, at));
        m.beats.splice(at, 0, TEMPLATES[kind || 'say'](m, at));
        return at;
      },
      remove(m, i) {
        if (i === 0 || m.beats.length < 2) return false;
        snap(m); m.beats.splice(i, 1); return true;
      },
      duplicate(m, i) {
        snap(m);
        m.beats.splice(i + 1, 0, JSON.parse(JSON.stringify(m.beats[i])));
        delete m.beats[i + 1].start;
        return i + 1;
      },
      move(m, from, to) {
        if (from === 0 || to === 0 || from === to) return from;
        snap(m);
        const [b] = m.beats.splice(from, 1);
        to = Math.max(1, Math.min(m.beats.length, to));
        m.beats.splice(to, 0, b);
        return to;
      },
      addAction(m, i, kind) {
        const b = m.beats[i];
        if (kind in b) return { ok: false, why: `beat already has ${kind}` };
        if ((kind === 'say' && b.objective != null) || (kind === 'objective' && b.say))
          return { ok: false, why: 'one message panel per beat — the counter only advances once' };
        snap(m);
        Object.assign(b, TEMPLATES[kind](m, i));
        return { ok: true };
      },
      removeAction(m, i, kind) {
        snap(m);
        delete m.beats[i][kind];
        if (kind === 'gate') delete m.beats[i].wait;
        return { ok: true };
      },
      // begin() before a typing burst, poke() per keystroke — so undo steps by
      // edit, not by character.
      begin(m) { snap(m); },
      poke(m, i, path, value) {
        const p = path.split('.');
        let o = m.beats[i];
        while (p.length > 1) o = o[p.shift()];
        o[p[0]] = value;
      },
      set(m, i, path, value) { snap(m); Model.poke(m, i, path, value); },
      TEMPLATES,
    };
  })();

  return {
    onoff, esc, brk, sayClass, SAY_COLOR,
    numberBeats, advanceOf, actionsOf, geoOf, stateAt, alwaysOn,
    lint, emitLadder, ladderText, drawMap, parseYaml, toYaml, Model,
  };
})();
