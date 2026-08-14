/* The model, and the prediction renderer.
 *
 * Nothing here is layout. This is what the editor has to agree with the compiler
 * about, and every piece of it was checked against campaign/build.py rather than
 * written to match:
 *   - beat numbering, identical to build.py's number_beats() (it reproduced the
 *     committed mods/act2m1.gml rung for rung)
 *   - the action vocabulary of one beat and its geometry
 *   - cumulative mission state at beat N, which is what scrubbing shows
 *   - the canvas predicted view
 *   - a YAML-subset parser and writer, diffed against PyYAML on ep9.yaml and
 *     round-tripped back to itself
 *   - a ladder emitter mirroring build.py's Emitter, so the GML that a beat will
 *     compile to is visible while it is being written
 *   - the lint checks build.py enforces, so the editor refuses what the build
 *     would reject rather than finding out at save time
 *
 * The server lints again with build.py itself before writing anything. This copy
 * exists to be instant, not to be authoritative.
 */
window.Core = (function () {
  'use strict';

  // ---------------------------------------------------------------- helpers
  const onoff = (v) => (v === true ? 'on' : v === false ? 'off' : v);
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

  // ------------------------------------------------------------- the storm
  // Bumped on every in-place write to a mask row; see Storm.set and Storm.puffs.
  let maskGen = 0, puffMemo = null;

  /* The painted field, in exactly the terms build.py's Storm class uses: one
     mask over the room, `.` clear, `#` damaging, `@` hot. It is stored as an
     array of row strings because that is what it looks like in the YAML — a
     picture — and a picture is the thing the editor is painting.

     Everything else (the row runs the game draws, where a cloud sits) is derived
     from it here the same way it is derived there, so the prediction and the
     mission agree by construction rather than by being kept in step. */
  const Storm = {
    CELL: 50,
    cell: (m) => (m.storm && m.storm.cell) || Storm.CELL,
    cols: (m) => Math.ceil(m.room.width / Storm.cell(m)),
    rows: (m) => Math.ceil(m.room.height / Storm.cell(m)),

    /* A mask that is short or ragged is legal in the file — nobody should have
       to pad 40 rows of dots by hand — so it is squared up before use. */
    ensure(m) {
      if (!m.storm) m.storm = { cell: Storm.CELL, dmg: 0.3, hot: 0.4, density: 0.18, lightning: 90, mask: [] };
      const cols = Storm.cols(m), rows = Storm.rows(m);
      const src = m.storm.mask || [];
      const out = [];
      for (let r = 0; r < rows; r++) {
        const line = String(src[r] == null ? '' : src[r]).slice(0, cols).replace(/[^.#@]/g, '.');
        out.push(line + '.'.repeat(cols - line.length));
      }
      m.storm.mask = out;
      return m.storm;
    },
    get(m, c, r) {
      const row = (m.storm && m.storm.mask && m.storm.mask[r]) || '';
      const ch = row[c];
      return ch === '#' ? 1 : ch === '@' ? 2 : 0;
    },
    set(m, c, r, v) {
      const st = Storm.ensure(m);
      if (c < 0 || r < 0 || c >= Storm.cols(m) || r >= Storm.rows(m)) return false;
      const ch = '.#@'[v];
      const row = st.mask[r];
      if (row[c] === ch) return false;
      st.mask[r] = row.slice(0, c) + ch + row.slice(c + 1);
      maskGen++;                        // the puff memo's only invalidator
      return true;
    },
    any(m) {
      return !!(m.storm && (m.storm.mask || []).some((r) => /[#@]/.test(r)));
    },
    /* Row runs — the rectangles the game's Draw fills, so the prediction has the
       same silhouette including the 50-unit staircase at the edges. */
    spans(m) {
      const out = [], cell = Storm.cell(m), cols = Storm.cols(m), rows = Storm.rows(m);
      for (let r = 0; r < rows; r++) {
        let c0 = -1;
        for (let c = 0; c <= cols; c++) {
          const v = c < cols ? Storm.get(m, c, r) : 0;
          if (v && c0 < 0) c0 = c;
          else if (!v && c0 >= 0) { out.push([c0 * cell, r * cell, (c - c0) * cell]); c0 = -1; }
        }
      }
      return out;
    },
    /* Where the gas clouds land, by the same rule the storm object uses: a cell
       on the boundary almost always gets one (they are what hides the wash's
       hard edge), an interior cell gets one at `density`. Seeded, so the map does
       not reshuffle on every repaint — the game re-scatters per entry, which is
       why the ghost overlay skips them. */
    puffs(m) {
      const cell = Storm.cell(m), cols = Storm.cols(m), rows = Storm.rows(m);
      const dens = m.storm && m.storm.density != null ? m.storm.density : 0.18;
      const mask = (m.storm || {}).mask;
      // Memoised, because this is a full scan of the mask — every cell, four
      // neighbour lookups and up to four PRNG draws each — and it is called
      // from drawMap, which now repaints per pointer event during a pan. EP9's
      // mask is 767 filled cells of 4000. The result is read and never
      // mutated, so handing the same array back is safe.
      //
      // Keyed on the mask's identity *and* a counter, because the two ways it
      // changes are different: Storm.ensure replaces the array (new identity),
      // Storm.set rewrites one row in place (same identity) and bumps the gen.
      if (puffMemo && puffMemo.mask === mask && puffMemo.gen === maskGen
          && puffMemo.cell === cell && puffMemo.dens === dens) return puffMemo.out;
      const rnd = mulberry32(20260808);
      const out = [];
      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          const v = Storm.get(m, c, r);
          if (!v) continue;
          const edge = c === 0 || r === 0 || c === cols - 1 || r === rows - 1
            || !Storm.get(m, c - 1, r) || !Storm.get(m, c + 1, r)
            || !Storm.get(m, c, r - 1) || !Storm.get(m, c, r + 1);
          if (rnd() >= (edge ? 0.5 : dens)) { rnd(); rnd(); rnd(); continue; }
          out.push({ x: (c + rnd()) * cell, y: (r + rnd()) * cell, k: 1 + rnd() * 1.2, hot: v === 2 });
        }
      }
      puffMemo = { mask: mask, gen: maskGen, cell: cell, dens: dens, out: out };
      return out;
    },
    /* A round brush, in cells. Returns true if anything changed, so a drag that
       stays inside one cell does not push an undo step per pointermove. */
    paint(m, wx, wy, radius, value) {
      const cell = Storm.cell(m);
      const cc = Math.floor(wx / cell), cr = Math.floor(wy / cell);
      const rad = Math.max(0, radius - 1);
      let hit = false;
      for (let r = cr - radius; r <= cr + radius; r++)
        for (let c = cc - radius; c <= cc + radius; c++)
          if ((c - cc) * (c - cc) + (r - cr) * (r - cr) <= rad * rad + rad)
            hit = Storm.set(m, c, r, value) || hit;
      return hit;
    },
  };

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

  /* What to call a spawn. It names either a game object or a ship design file,
     and the file reads better as its bare name than as the path the loader
     gets. Mirrors spawn_label() in campaign/build.py — the Python side learned
     this the hard way, having assumed `object` was always there. */
  function spawnLabel(sp) {
    if (sp.ship) return String(sp.ship).replace(/\\/g, '/').split('/').pop();
    return sp.object;
  }

  /* The `image_angle` the compiler will leave on a spawn — the one answer every
     draw path here asks for, because there are two keys that reach it and they
     do not reach it the same way.

     `facing:` is a fixture (`direction` *and* `image_angle`) and applies to both
     kinds of spawn. `angle:` is a look override, `image_angle` alone, and
     build.py emits the look block *before* the fixtures — so where a spawn
     carries both, facing is the assignment that lands last and wins. A `ship:`
     spawn gets the fixtures and nothing else: `angle:` on a design is a key the
     compiler never emits, which is why it must not rotate one here either.

     Undefined, not 0, when neither key applies: every caller passes this straight
     to a rotate that treats a falsy angle as "do not rotate". */
  function imageAngle(sp) {
    const a = sp.facing != null ? sp.facing : (sp.ship ? null : sp.angle);
    return a == null ? undefined : a;
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
    // First, and it compiles to nothing: a note is about the beat, not a thing
    // the beat does. It earns an icon anyway — a beat carrying reasoning nobody
    // can see from the track is a note nobody will read.
    if (b.note != null) push('note', '✎', 'note', noteText(b.note).split('\n')[0] || 'empty');
    if (b.music === 'stop') push('music', '♫', 'music', 'stop');
    else if (b.music) push('music', '♫', 'music', String(b.music));
    if (onoff(b.eerie) === 'on') push('eerie', '◌', 'ambience', 'snd_eeriesound loop');
    else if (onoff(b.eerie) === 'off') push('eerie', '◌', 'ambience', 'stop eerie');
    if (onoff(b.interference) === 'on') push('interference', '≋', 'interference', 'nebula flare + hull distortion');
    else if (onoff(b.interference) === 'off') push('interference', '≋', 'interference', 'clear');
    if (b.autosave) push('autosave', '◉', 'autosave', 'unless difficulty = Hard');
    if (b.camera) push('camera', '▣', 'camera', `(${b.camera.x}, ${b.camera.y}) speed ${b.camera.speed == null ? 60 : b.camera.speed}`,
      { type: 'camera', x: b.camera.x, y: b.camera.y });
    (b.spawn || []).forEach((sp) => push('spawn', '◆', 'spawn',
      `${spawnLabel(sp)}${sp.damage ? ` (damaged ${sp.damage})` : ''} at (${sp.x}, ${sp.y})${sp.name ? ' as ' + sp.name : ''}`,
      { type: 'spawn', x: sp.x, y: sp.y, label: spawnLabel(sp) }));
    if (b.ping != null) {
      const at = pingAt(m, b);
      push('ping', '◎', 'ping',
        Array.isArray(b.ping) ? `(${b.ping[0]}, ${b.ping[1]})`
          : at ? `follows ${b.ping}` : `follows ${b.ping} — no such spawn`,
        at ? { type: 'ping', x: at.x, y: at.y } : null);
    }
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
      spawns: [], gatesDone: [], activeGate: null, meteors: false, interference: false,
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
      if (onoff(b.interference) === 'on') st.interference = true;
      if (onoff(b.interference) === 'off') st.interference = false;
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

  // ---------------------------------------------------------------- the lint
  // Same rules build.py enforces; the editor should never let you author past them.
  const BEAT_KEYS = ['note', 'start', 'say', 'objective', 'gate', 'gate_at', 'wait', 'autosave',
    'music', 'eerie', 'meteors', 'camera', 'spawn', 'ping', 'win', 'exec', 'interference'];

  /* `note:` — why this beat is the way it is, carried *as data*.
   *
   * A `#` comment cannot do this job. The editor parses the YAML into a model
   * and writes the file back out of that model, so a comment survives exactly
   * until the next save and then is gone without a trace. That is not a
   * hypothetical: a measured derivation of a camera position and the reasoning
   * behind four hulls' placement were both written as comments and both erased
   * by the next apply.
   *
   * A note is a list of lines rather than one long string because the file's
   * YAML subset has no block scalars, and because a list of lines diffs by the
   * line — the same reason the storm mask is one. It compiles to nothing.
   */
  const noteLines = (v) => (v == null ? [] : Array.isArray(v) ? v.map(String) : [String(v)]);
  const noteText = (v) => noteLines(v).join('\n');
  /* Double quotes are the one character the writer cannot represent — it quotes
     every line and the format has no escape — so they become typographic ones
     on the way in, where it is visible, rather than corrupting the file later. */
  const noteFrom = (text) => String(text).replace(/"/g, '”').split('\n');

  /* The look block: assignments the compiler makes after `instance_create`, i.e.
     after the object's own Create event, so they replace whatever it chose for
     itself — and therefore the ones only an `object:` spawn ever gets. Mirrors
     build.py's `Emitter.LOOK_KEYS`, in the same order, so the warning the two of
     them share names the keys the same way. */
  const LOOK_KEYS = ['sprite', 'scale', 'angle', 'frame', 'tint'];

  /* A spawn is an object at a position, plus — optionally — that look. In YAML
     order, which is also the card's. The look keys are spread in rather than
     re-typed as this list's tail: SPAWN_KEYS is the key *order* the writer
     emits, so it is a plausible thing to reorder, and a hand-copied tail would
     go on lint-checking the wrong five with nothing to say so. */
  const SPAWN_KEYS = ['object', 'ship', 'team', 'hold', 'facing', 'damage',
    'x', 'y', 'name', ...LOOK_KEYS];
  //: The three the compiler maps onto importShip's team argument.
  const TEAMS = ['player', 'ally', 'enemy'];
  /* What a team looks like. The game tints a hull by the side it spawns into —
     which is why a ship file records a shade index and not a colour — so the
     prediction has to tint too, or an enemy would draw in friendly green.
     Shade 0 of each palette, from bfdefault.ini via tools/bsf/sprites.py. */
  const TEAM_TINT = { player: 'rgb(0,255,0)', ally: 'rgb(0,255,255)', enemy: 'rgb(255,0,0)' };
  // The same names build.py's Emitter.TINTS resolves, in the same channels — the
  // prediction and the mission have to mean the same colour by construction.
  const TINT_RGB = {
    white: [255, 255, 255], red: [255, 90, 77], green: [78, 240, 138], blue: [127, 216, 255],
    amber: [255, 182, 72], magenta: [255, 92, 255], grey: [150, 150, 150], gray: [150, 150, 150],
  };
  const TINTS = ['white', 'red', 'green', 'blue', 'amber', 'magenta', 'grey'];
  function tintCSS(v) {
    const s = String(v).trim();
    const named = TINT_RGB[s.toLowerCase()];
    if (named) return `rgb(${named.join(',')})`;
    return /^#?[0-9a-fA-F]{6}$/.test(s) ? '#' + s.replace(/^#/, '') : null;
  }

  /* How far a fixed ping may sit from the thing it announces before it stops
     looking deliberate. Mirrors PING_NEAR in campaign/build.py; a big hull is a
     few hundred units across, so pointing at a station's origin passes wherever
     its art ends. The case it exists for was out by 926. */
  const PING_NEAR = 500;

  /* Everything a ping may be attached to, as { name: {x, y, what} }. Mirrors
     ping_anchors() in campaign/build.py — the compiler resolves the link, so
     the two must agree about what is nameable or the map draws a ping the build
     will not emit. */
  function pingAnchors(m) {
    const out = { player: { x: m.player.x, y: m.player.y, what: m.player.object } };
    m.beats.forEach((b, bi) => (b.spawn || []).forEach((sp) => {
      if (sp.name) out[sp.name] = { x: sp.x, y: sp.y, what: spawnLabel(sp), bi: bi };
    }));
    return out;
  }

  /* `ping:` as a point, whichever form it is in: a pair is a fixed point, a
     string is the name of the spawn it follows. Null when a link does not
     resolve — the lint says so, and drawing nothing beats drawing (0, 0).

     `anchors` is the table pingAnchors() builds, passed in by callers looping
     over every beat: building it walks every beat and every spawn, so doing it
     per beat is the same walk N times over. */
  function pingAt(m, b, anchors) {
    const p = b && b.ping;
    if (p == null) return null;
    if (Array.isArray(p)) return { x: p[0], y: p[1] };
    const a = (anchors || pingAnchors(m))[String(p)];
    return a ? { x: a.x, y: a.y } : null;
  }

  /* Findings carry `warn: true` or nothing. The build has always had both
     severities; this side had only the blocking kind, which is why a rule that
     is *usually* right had nowhere to live — and a rule that can only fail the
     build is a rule you cannot write. */
  function lint(m) {
    const errs = [];
    const anchors = pingAnchors(m);
    const warn = (where, msg) => errs.push({ where, msg, warn: true });
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
      // Both forms of ping:. A link that resolves to nothing is an error — the
      // build drops the ping entirely, and silently losing the thing that tells
      // the player where to look is not a playtest discovery. A *fixed* ping far
      // from every spawn in its own beat is a warning that recommends the link:
      // it cannot be an error, because pointing at a place rather than a thing
      // is legal and nothing here can tell which was meant.
      if (b.ping != null && !Array.isArray(b.ping)) {
        const have = Object.keys(anchors);
        if (have.indexOf(String(b.ping)) < 0)
          errs.push({ where, msg: `ping follows '${b.ping}', which is not a named spawn `
            + `or 'player' (have: ${have.sort().join(', ') || 'none'})` });
      } else if (b.ping && (b.spawn || []).length) {
        let best = null, bd = Infinity;
        b.spawn.forEach((sp) => {
          const d = Math.hypot(sp.x - b.ping[0], sp.y - b.ping[1]);
          if (d < bd) { bd = d; best = sp; }
        });
        if (bd > PING_NEAR)
          warn(where, `ping (${b.ping[0]}, ${b.ping[1]}) is ${Math.round(bd)} units from `
            + `${spawnLabel(best)}, the nearest spawn in the same beat. If it is meant to `
            + 'announce that spawn, attach it in the ping card — a fixed pair does not '
            + 'move when the spawn does');
      }
    });
    if (m.fail) text(m.fail.ship, 'fail.ship');
    // The room is the world, and it is editable now, so shrinking it can strand
    // things outside it. A beacon out there is a mission that cannot be
    // finished and a ship out there never arrives — both worth stopping at the
    // lint rather than at the playtest. The camera and pings clamp harmlessly.
    (function bounds() {
      const W = m.room.width, H = m.room.height;
      const out = (x, y) => x < 0 || y < 0 || x > W || y > H;
      const where = `the ${W}×${H} room`;
      if (out(m.player.x, m.player.y))
        errs.push({ where: 'player', msg: `start (${m.player.x}, ${m.player.y}) is outside ${where}` });
      (m.gates || []).forEach((g, i) => {
        if (out(g.x, g.y)) errs.push({ where: `gate ${i + 1}`, msg: `beacon (${g.x}, ${g.y}) is outside ${where} — the ship can never reach it` });
      });
      m.beats.forEach((b, i) => {
        (b.spawn || []).forEach((sp) => {
          const what = spawnLabel(sp);
          if (out(sp.x, sp.y)) errs.push({ where: `beat ${i}`, msg: `${what} spawns at (${sp.x}, ${sp.y}), outside ${where}` });
          Object.keys(sp).forEach((k) => {
            if (SPAWN_KEYS.indexOf(k) < 0) errs.push({ where: `beat ${i}`, msg: `unknown spawn key '${k}'` });
          });
          // A spawn names an object or a design, never both — and a design has
          // no safe default side, so `team:` is required rather than assumed.
          if (sp.ship && sp.object)
            errs.push({ where: `beat ${i}`, msg: 'a spawn is either object: or ship:, not both' });
          if (!sp.ship && !sp.object)
            errs.push({ where: `beat ${i}`, msg: 'a spawn needs object: or ship:' });
          if (sp.ship && !sp.team)
            errs.push({ where: `beat ${i}`, msg: `ship spawns need team: (${TEAMS.join(' | ')})` });
          if (sp.team && TEAMS.indexOf(String(sp.team)) < 0)
            errs.push({ where: `beat ${i}`, msg: `team '${sp.team}' is not ${TEAMS.join(' | ')}` });
          if (sp.ship && window.Ships && Ships.state.list.length && !Ships.info(sp.ship))
            errs.push({ where: `beat ${i}`, msg: `no such ship design '${sp.ship}'` });
          // The look block compiles for `object:` spawns only — a design gets
          // importShip and the three fixtures, and build.py emits nothing else
          // for it. The card never offers these on a design, so they can only
          // arrive by hand; unsaid, `angle: 90` on a design would read as a
          // rotation that neither the map nor the game will ever perform.
          if (sp.ship) {
            const dead = LOOK_KEYS.filter((k) => sp[k] != null);
            if (dead.length)
              warn(`beat ${i}`, `${dead.join(', ')} on a design does nothing — the look `
                + 'block is assigned after instance_create and a design is loaded by '
                + 'importShip instead. To turn one, use facing:');
          // The other silent case, and the same shape: both keys write
          // image_angle, so on an object carrying both the file reads as if the
          // hull could travel one way and point another. It cannot — one of the
          // two assignments is simply overwritten — so say which.
          } else if (sp.angle != null && sp.facing != null) {
            warn(`beat ${i}`, 'angle: and facing: both set image_angle, so facing '
              + `wins and angle: ${sp.angle} is dead. Drop one.`);
          }
          if (sp.tint != null && TINTS.indexOf(String(sp.tint).toLowerCase()) < 0
              && !/^#?[0-9a-fA-F]{6}$/.test(String(sp.tint)))
            errs.push({ where: `beat ${i}`, msg: `tint '${sp.tint}' is not #rrggbb or one of ${TINTS.join(', ')}` });
          // damage is a multiplier on section HP, and the hull has to be
          // nameable because a mission-side tick holds it there every second.
          if (sp.damage != null) {
            const d = Number(sp.damage);
            if (!(d > 0 && d <= 1))
              errs.push({ where: `beat ${i}`, msg: `damage ${sp.damage} is out of range — it is a multiplier on section HP, so 0 < damage <= 1` });
            if (!sp.name)
              errs.push({ where: `beat ${i}`, msg: 'a damaged spawn needs name: — the hull has to be nameable for the damage to be held on it' });
          }
          const A = window.Assets;
          if (sp.sprite && A && A.ok && !A.sprites[sp.sprite])
            errs.push({ where: `beat ${i}`, msg: `sprite '${sp.sprite}' is not in the tree` });
        });
        if (b.gate_at && out(b.gate_at.x, b.gate_at.y))
          errs.push({ where: `beat ${i}`, msg: `gate_at (${b.gate_at.x}, ${b.gate_at.y}) is outside ${where}` });
      });
    })();
    if (m.storm) {
      const cols = Storm.cols(m), rows = Storm.rows(m);
      if ((m.storm.mask || []).length > rows)
        errs.push({ where: 'storm.mask', msg: `${m.storm.mask.length} rows, the room holds ${rows}` });
      (m.storm.mask || []).forEach((line, r) => {
        if (String(line).length > cols)
          errs.push({ where: `storm.mask row ${r}`, msg: `${String(line).length} wide, the room holds ${cols}` });
        const bad = String(line).replace(/[.#@]/g, '');
        if (bad) errs.push({ where: `storm.mask row ${r}`, msg: `'${bad[0]}' is not one of . # @` });
      });
    }
    if (m.zones) errs.push({ where: 'zones', msg: 'zones: was replaced by storm: — build.py still rasterises it, but the editor paints the mask and would drop these circles on the next save' });
    return errs;
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
    // Returned as well as used: `zoom` is a multiple of this, so view.js needs
    // the fit itself to work out what a new zoom would scale to. Recomputing it
    // there would mean guessing at the padding this caller chose.
    const fit = Math.min((W - pad * 2) / m.room.width, (H - pad * 2) / m.room.height);
    const k = fit * (o.zoom || 1);
    let ox = (W - m.room.width * k) / 2, oy = (H - m.room.height * k) / 2;
    if (o.center) { ox = W / 2 - o.center.x * k; oy = H / 2 - o.center.y * k; }
    const X = (x) => ox + x * k, Y = (y) => oy + y * k, S = (r) => r * k;
    // The six theme tokens this function draws with, read once. `c()` used to be
    // called per gate, per ping and per spawn — forty property lookups a frame,
    // at pointer rate during a pan.
    const css = getComputedStyle(document.documentElement);
    const c = (n) => css.getPropertyValue(n).trim();
    const RULE = c('--rule'), PHOS = c('--phos'), HOT = c('--phos-hot'),
      DIM = c('--ink-dim'), ALIEN = c('--alien');
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
    /* Nothing outside the room may draw over the chrome. Written as a wrapper
       for the same reason `world` is: three hand-rolled save/clip/restore
       triples is three chances to add a save without its restore, and a leaked
       clip corrupts every later frame rather than the one that caused it. */
    const inRoom = (fn) => {
      ctx.save();
      ctx.beginPath(); ctx.rect(X(0), Y(0), S(m.room.width), S(m.room.height)); ctx.clip();
      fn();
      ctx.restore();
    };
    const label = (text, x, y, color, px) => {
      ctx.fillStyle = color;
      ctx.font = (px || 10) + 'px ui-monospace, monospace';
      ctx.textAlign = 'center';
      ctx.fillText(text, x, y);
    };

    ctx.fillStyle = '#04070a'; ctx.fillRect(0, 0, W, H);
    // room + grid
    inRoom(() => {
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
    });
    ctx.strokeStyle = RULE; ctx.lineWidth = 1; ctx.strokeRect(X(0), Y(0), S(m.room.width), S(m.room.height));

    // The storm, drawn the only way the game draws it: as its gas clouds. There
    // is no outline and no tint under them on purpose — the mission has neither,
    // and a prediction that added one would be quietly promising the player an
    // edge they will not be able to see.
    if (Storm.any(m)) inRoom(() => {
      if (art && art.spriteOf('ter_Nebula')) {
        Storm.puffs(m).forEach((p) => world(() => art.drawObject(ctx, 'ter_Nebula', p.x, p.y,
          { tint: p.hot ? 'rgb(255,150,70)' : 'rgb(210,45,38)', alpha: 0.20, scale: p.k })));
      } else {
        // No art: fall back to the cells themselves, so the field is still
        // visible rather than absent.
        const cell = Storm.cell(m);
        ctx.fillStyle = 'rgba(255,60,50,0.14)';
        Storm.spans(m).forEach(([sx, sy, sw]) => ctx.fillRect(X(sx), Y(sy), S(sw), S(cell) + 0.5));
      }
    });
    // The brush, and the cell grid it snaps to — only while the tool is up.
    if (o.paint) inRoom(() => {
      const cell = Storm.cell(m);
      if (S(cell) > 4) {
        ctx.strokeStyle = 'rgba(255,120,110,0.10)'; ctx.lineWidth = 1;
        ctx.beginPath();
        for (let gx = 0; gx <= m.room.width; gx += cell) { ctx.moveTo(X(gx), Y(0)); ctx.lineTo(X(gx), Y(m.room.height)); }
        for (let gy = 0; gy <= m.room.height; gy += cell) { ctx.moveTo(X(0), Y(gy)); ctx.lineTo(X(m.room.width), Y(gy)); }
        ctx.stroke();
      }
      if (o.paint.at) {
        const cc = Math.floor(o.paint.at.x / cell), cr = Math.floor(o.paint.at.y / cell);
        ctx.strokeStyle = o.paint.erase ? 'rgba(127,216,255,0.9)' : o.paint.level === 2 ? 'rgba(255,180,80,0.9)' : 'rgba(255,90,77,0.9)';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(X((cc + 0.5) * cell), Y((cr + 0.5) * cell), S(o.paint.radius * cell), 0, 6.284);
        ctx.stroke();
      }
    });

    /* Is this the thing the pointer is on (or dragging)? handles.js addresses
       everything draggable the same way, so one comparison serves every kind. */
    const hv = (o.handles && o.handles.hover) || null;
    const grabbed = (a) => !!hv && hv.kind === a.kind && hv.i === a.i && hv.bi === a.bi && hv.si === a.si;

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
      const held = grabbed({ kind: 'gate', i: i });
      ctx.beginPath(); ctx.arc(X(g2.x), Y(g2.y), Math.max(5, S(70)), 0, 6.284);
      ctx.strokeStyle = held ? HOT
        : active ? HOT : done ? 'rgba(78,240,138,0.85)' : on ? 'rgba(78,240,138,0.5)' : 'rgba(78,240,138,0.18)';
      ctx.lineWidth = held ? 3 : active ? 2.5 : 1.5; ctx.stroke();
      if (done) { ctx.fillStyle = 'rgba(78,240,138,0.30)'; ctx.fill(); }
      if (o.labels !== false)
        label(held ? `${i + 1}  ${g2.x}, ${g2.y}` : String(i + 1),
          X(g2.x), Y(g2.y) - Math.max(9, S(70)) - 4,
          held ? HOT : on ? DIM : 'rgba(139,156,149,0.3)');
    });

    /* `gate_at` — a beacon typed straight onto a beat instead of referenced from
       `gates:`. The route already bent through these points and nothing was
       drawn on them, which was survivable while they were read-only and is not
       now: a handle you cannot see is worse than no handle. Marked like a gate,
       square rather than round, because it belongs to one beat. */
    m.beats.forEach((b, bi) => {
      if (!b.gate_at) return;
      const held = grabbed({ kind: 'gate_at', bi: bi });
      const on = lit({ type: 'gate', x: b.gate_at.x, y: b.gate_at.y });
      const gx = X(b.gate_at.x), gy = Y(b.gate_at.y), gs = Math.max(5, S(70));
      if (art) world(() => art.drawObject(ctx, 'MoveToArea', b.gate_at.x, b.gate_at.y,
        { frame: 6, alpha: held ? 1 : on ? 0.8 : 0.35, scale: 2 }));
      ctx.strokeStyle = held ? HOT : on ? 'rgba(78,240,138,0.5)' : 'rgba(78,240,138,0.18)';
      ctx.lineWidth = held ? 3 : 1.5;
      ctx.strokeRect(gx - gs, gy - gs, gs * 2, gs * 2);
      if (o.labels !== false && held)
        label(`beat ${bi}  ·  ${b.gate_at.x}, ${b.gate_at.y}`, gx, gy - gs - 4, HOT);
    });

    /* Pings. `showPing` is the sonar flash that tells the player where to look,
       and it had no marker on the map at all — only the focused beat's ring
       showed one, which is a handle you can see for one beat out of twenty-three
       and a position you could not check on any of the others.

       Drawn as two rings, because that is what the flash looks like, and in the
       ping card's own blue so the map and the rail agree. A *linked* ping is
       drawn hollow: it has no position of its own to grab, and the thing to
       drag is the spawn it follows. */
    const anchors = pingAnchors(m);
    m.beats.forEach((b, bi) => {
      const at = pingAt(m, b, anchors);
      if (!at) return;
      const link = !Array.isArray(b.ping);
      const held = grabbed({ kind: 'ping', bi: bi });
      const on = lit({ type: 'ping', x: at.x, y: at.y });
      const ax = X(at.x), ay = Y(at.y), ar = Math.max(4, S(70));
      ctx.strokeStyle = held ? HOT
        : on ? 'rgba(122,160,200,0.85)' : 'rgba(122,160,200,0.28)';
      ctx.lineWidth = held ? 2.5 : 1.5;
      ctx.setLineDash(link ? [3, 4] : []);
      [0.5, 0.85].forEach((f) => {
        ctx.beginPath(); ctx.arc(ax, ay, ar * f, 0, 6.284); ctx.stroke();
      });
      ctx.setLineDash([]);
      if (o.labels !== false && held)
        label(`ping · beat ${bi} · ${at.x}, ${at.y}`, ax, ay - ar - 4, HOT);
    });

    // scripted spawns (all of them, or only those already fired when scrubbing)
    const spawns = [];
    m.beats.forEach((b, bi) => (b.spawn || []).forEach((sp, si) => spawns.push({ sp, bi, si })));
    // an object as the game would draw it: a real hull if the render-model dump
    // has one, else the object's own sprite with its own blend
    function drawActor(sp, wx, wy, alpha, team) {
      if (!art) return false;
      // Both branches turn: the hull because every section places itself at
      // `l_offsetdir + l_owner.image_angle`, the sprite because that is what
      // image_angle means. This is the whole of what `facing:` does to a hull
      // that never moves — four berthed ships drew nose-right on the map and
      // nose-in in the game, and only the game was rotating them.
      const obj = sp.object, angle = imageAngle(sp);
      // A look override replaces the object's own sprite, so a hull would be
      // drawing something the game will not: `sprite_index` is assigned after
      // Create and the prediction has to agree.
      if (!sp.sprite) {
        const hull = art.ship(obj);
        if (hull) {
          let ok = false;
          world(() => {
            ctx.globalAlpha = alpha;
            ok = art.drawShip(ctx, hull, wx, wy, { team: team || 0, angle: angle });
            ctx.globalAlpha = 1;
          });
          if (ok) return true;
        }
      }
      // `angle` is resolved for every record, the player's included, so it goes
      // in the literal; the rest are look keys the player start does not have.
      const o2 = { alpha: alpha, angle: angle };
      if (sp.scale != null) o2.scale = sp.scale;
      if (sp.frame != null) o2.frame = sp.frame;
      if (sp.tint != null) o2.tint = tintCSS(sp.tint);
      let drew = false;
      world(() => {
        drew = sp.sprite
          ? art.blit(ctx, sp.sprite, wx, wy, Object.assign(
            { tint: art.sprites[sp.sprite] && art.sprites[sp.sprite].mask ? 'rgb(255,255,255)' : null }, o2))
          : art.drawObject(ctx, obj, wx, wy, o2);
      });
      return drew;
    }

    spawns.forEach(({ sp, bi, si }) => {
      const shown = st ? bi <= o.reveal : true;
      const on = lit({ type: 'spawn', x: sp.x, y: sp.y });
      const held = grabbed({ kind: 'spawn', bi: bi, si: si });
      const alpha = held ? 1 : shown ? (on ? 1 : 0.5) : 0.18;
      // A design is drawn from its own scene — the same draw list the ship CLI
      // renders — so the map shows the hull the game will build, not a stand-in.
      let real;
      if (sp.ship) {
        real = false;
        if (window.Ships) {
          world(() => {
            real = Ships.draw(ctx, sp.ship, sp.x, sp.y,
              { alpha: alpha, angle: imageAngle(sp), tint: TEAM_TINT[sp.team] });
          });
        }
      } else {
        real = drawActor(sp, sp.x, sp.y, alpha,
          /ally|Allied|Space|Hestia/.test(sp.object) ? 1 : 2);
      }
      ctx.globalAlpha = held ? 1 : shown ? (on ? 1 : 0.28) : 0.13;
      ctx.strokeStyle = held ? HOT : ALIEN; ctx.lineWidth = held ? 2.5 : 1.5;
      // A design's bracket fits the hull it drew; an object's is the old 60.
      const s2 = Math.max(5, S(sp.ship && window.Ships ? Ships.radius(sp.ship) : 60));
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
        // Held, the label says which beat it fires on and where it is — a spawn
        // belongs to exactly one beat, and the map draws later beats' spawns
        // too, so "which one am I moving" is the question to answer here.
        const nm = (sp.ship && (Ships.info(sp.ship) || {}).name) || spawnLabel(sp);
        label(held ? `${nm}  ·  beat ${bi}  ·  ${sp.x}, ${sp.y}` : nm,
          X(sp.x), Y(sp.y) - s2 - 5, held ? HOT : ALIEN);
      }
      ctx.globalAlpha = 1;
    });

    // player start
    const px = X(m.player.x), py = Y(m.player.y);
    const pheld = grabbed({ kind: 'player' });
    // The player start is a spawn record with a subset of the keys — the
    // compiler creates it the same way — so it goes through the same door
    // rather than through a call shaped specially for it.
    if (!drawActor(m.player, m.player.x, m.player.y, 1, 0)) {
      ctx.fillStyle = PHOS;
      ctx.beginPath(); ctx.moveTo(px + 8, py); ctx.lineTo(px - 6, py - 6); ctx.lineTo(px - 6, py + 6); ctx.closePath(); ctx.fill();
    }
    if (pheld) {
      ctx.beginPath(); ctx.arc(px, py, Math.max(6, S(70)), 0, 6.284);
      ctx.strokeStyle = HOT; ctx.lineWidth = 3; ctx.stroke();
    }
    if (o.labels !== false)
      label(pheld ? `${m.player.object.toUpperCase()}  ·  ${m.player.x}, ${m.player.y}` : m.player.object.toUpperCase(),
        px, py - Math.max(14, S(70)), pheld ? HOT : PHOS, 9);

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
        ctx.strokeStyle = HOT; ctx.lineWidth = 1; ctx.globalAlpha = 0.8; ctx.stroke(); ctx.globalAlpha = 1;
      });
    }
    return { X, Y, S, k, ox, oy, fit };
  }

  // ------------------------------------------------------------ YAML out
  // The editor's edits have to come back out as the DSL or none of this counts.
  // Style follows missions/ep9.yaml: block maps, flow maps for coordinates.
  //
  // ⚠ A YAML writer built from a parsed model cannot preserve comments, and a
  // saved mission that quietly lost the notes explaining what `damage` or a zone
  // `dmg` means would be a bad trade for an editor nobody has to use. So the
  // comments are emitted rather than preserved: they document the *DSL*, not any
  // one mission, which makes them the writer's to own. Every comment ep9.yaml
  // was hand-written with is in this table, so the first save is a no-op on them.
  const NOTE = {
    header: [
      '# Beat script for campaign/build.py. Source narrative: campaign/ACT-II.md.',
      '#',
      "# Text rules: '#' is a line break (the game's own convention), apostrophes are",
      '# fine (they compile to plain double-quoted globals), double quotes and em',
      '# dashes are not (font + quoting) — the linter enforces this.',
      '#',
      '# Written by tools/editor. Hand-editing is fine; the editor rewrites the file',
      '# in this shape on every save.',
    ],
    mission: 'global.mission value this episode answers to',
    damage: 'section HP multiplier at spawn',
    nebula: 'ter_Nebula scattered over the room at create',
    storm: ["# The storm — a painted field, not a list of circles. One cell is `cell`",
      "# world units; '#' costs a section `dmg` HP per step, '@' costs `hot`, '.' is",
      '# clear space. The red gas clouds are drawn from these same cells, so what',
      '# you can see is exactly what bites. Paint it in tools/editor.'],
    density: 'gas-cloud puffs per filled cell',
    lightning: 'average frames between strikes (0 = none)',
    gates: ['# Dead beacons flown in order (MoveToArea gates).'],
    interval: 'frames between spawn attempts while on',
    cap: 'max live obs_Meteor',
  };

  function toYaml(m) {
    const q = (s) => `"${String(s)}"`;
    const qw = (s) => (/^[A-Za-z][A-Za-z0-9 ._-]*$/.test(s) ? s : q(s));
    // A tint is written `#ff8844`, and `#` opens a comment in YAML — so a string
    // that is not a plain scalar gets quoted. Numbers must not: `x: "2760"` reads
    // back as a string and every consumer of it is arithmetic.
    const fv = (v) => (typeof v === 'string' && !/^[A-Za-z][A-Za-z0-9 ._-]*$/.test(v) ? q(v) : v);
    const flow = (o, keys) => '{' + keys.filter((k) => o[k] != null).map((k) => `${k}: ${fv(o[k])}`).join(', ') + '}';
    const pad = (s, note) => (note ? s.padEnd(22) + '# ' + note : s);
    const L = [];
    L.push(`# Act II — Episode ${m.episode}: ${m.title}`, ...NOTE.header, '');
    L.push(`id: ${m.id}`, `episode: ${m.episode}`, pad(`mission: ${m.mission}`, NOTE.mission),
      `title: ${m.title}`, `subtitle: ${m.subtitle}`, '');
    L.push('room:', `  width: ${m.room.width}`, `  height: ${m.room.height}`,
      `  caption: ${m.room.caption}`, '');
    L.push('player:', `  object: ${m.player.object}`, `  x: ${m.player.x}`, `  y: ${m.player.y}`,
      pad(`  damage: ${m.player.damage}`, NOTE.damage), '');
    L.push('fail:', `  ship: ${q(m.fail.ship)}`, '');
    if (m.scenery) L.push('scenery:', pad(`  nebula: ${m.scenery.nebula}`, NOTE.nebula), '');
    if (Storm.any(m)) {
      const st = Storm.ensure(m);
      L.push(...NOTE.storm, 'storm:', `  cell: ${st.cell}`, `  dmg: ${st.dmg}`, `  hot: ${st.hot}`,
        pad(`  density: ${st.density}`, NOTE.density),
        pad(`  lightning: ${st.lightning}`, NOTE.lightning), '  mask:');
      // Trailing all-clear rows carry no information and would double the file
      // every time the room grew; the compiler pads a short mask back out.
      let last = st.mask.length - 1;
      while (last > 0 && !/[#@]/.test(st.mask[last])) last--;
      st.mask.slice(0, last + 1).forEach((row) => L.push(`    - "${row}"`));
      L.push('');
    }
    if (m.gates) { L.push(...NOTE.gates, 'gates:'); m.gates.forEach((g) => L.push('  - ' + flow(g, ['x', 'y']))); L.push(''); }
    if (m.meteors) L.push('meteors:', pad(`  interval: ${m.meteors.interval}`, NOTE.interval),
      pad(`  cap: ${m.meteors.cap}`, NOTE.cap), '');
    L.push('beats:');
    // `note` first: it is why the rest of the beat looks like this, and a reason
    // printed under its conclusion is a footnote rather than an explanation.
    const ORDER = ['note', 'start', 'music', 'eerie', 'interference', 'meteors', 'autosave', 'camera',
      'spawn', 'ping', 'objective', 'say', 'gate', 'gate_at', 'wait', 'win', 'exec'];
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
          v.forEach((sp) => rows.push('  - ' + flow(sp, SPAWN_KEYS)));
        } else if (k === 'camera') rows.push(`camera: ${flow(v, ['x', 'y', 'speed'])}`);
        else if (k === 'gate_at') rows.push(`gate_at: ${flow(v, ['x', 'y'])}`);
        // Two forms: a pair is a fixed point, a bare name is the spawn it
        // follows. The name is a plain scalar and needs no quoting — the picker
        // only ever writes identifiers.
        else if (k === 'ping') rows.push(Array.isArray(v) ? `ping: [${v[0]}, ${v[1]}]` : `ping: ${v}`);
        // One quoted line each, like the storm mask. Quoted because a note is
        // prose and will contain ':' and '#', both of which are structure to a
        // bare scalar; stripComment is quote-aware, so they survive.
        else if (k === 'note') { rows.push('note:'); noteLines(v).forEach((l) => rows.push(`  - ${q(l)}`)); }
        else if (k === 'objective') rows.push(`objective: ${q(v)}`);
        else if (k === 'eerie' || k === 'meteors' || k === 'interference')
          rows.push(`${k}: ${v === true ? 'on' : v === false ? 'off' : v}`);
        else if (k === 'exec') { rows.push('exec:'); v.forEach((e) => rows.push(`  - ${q(e)}`)); }
        else rows.push(`${k}: ${v}`);
      });
      rows.forEach((r, i) => L.push((i ? '    ' : '  - ') + r));
      L.push('');
    });
    return L.join('\n');
  }

  /* ------------------------------------------------- the dotted-path grammar
     `spawn.0.tint`, `room.width`, `say.who` — one grammar, one reader, one
     writer, rooted wherever the caller says. It was written out five times
     across three files, three of those readers differing only in whether they
     null-guarded, and `Model.poke` was hardcoded to root at a beat, which is
     why the mission sheet grew its own pair to reach `room.width` at all.

     getPath is null-safe: a path into an absent object is absent, not a throw.
     setPath creates the objects it walks through, and `undefined` deletes
     rather than assigns — the optional look keys on a spawn have no neutral
     value (`scale: 0` is invisible, `tint: ""` is not a colour), so clearing a
     field has to mean "the key is not there", which is the only thing the
     compiler reads as "leave it alone". */
  function getPath(root, path) {
    return path.split('.').reduce((o, k) => (o == null ? o : o[k]), root);
  }

  function setPath(root, path, value) {
    const ks = path.split('.');
    let o = root;
    for (let i = 0; i < ks.length - 1; i++) {
      if (o[ks[i]] == null) o[ks[i]] = {};
      o = o[ks[i]];
    }
    const last = ks[ks.length - 1];
    if (value === undefined) delete o[last];
    else o[last] = value;
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
      interference: () => ({ interference: true }),
      music: () => ({ music: 'theme' }),
      autosave: () => ({ autosave: true }),
      win: () => ({ win: true }),
      note: () => ({ note: [''] }),
      empty: () => ({}),
    };
    return {
      canUndo: () => past.length > 0,
      undo(m) { if (past.length) restore(m, past.pop()); },
      // A different mission is a different history; carrying the old stack over
      // would let undo paste one mission's beats into another.
      reset() { past.length = 0; },
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
      /* `spawn:` is the one verb that is a *list*, so it needs its own add and
         remove: the card's ✕ takes the whole verb off the beat, which is the
         wrong tool for one prop out of three, and `addAction` refuses a second
         `spawn` because the key already exists. */
      addSpawn(m, i) {
        snap(m);
        const b = m.beats[i];
        if (!b.spawn) b.spawn = [];
        const last = b.spawn[b.spawn.length - 1];
        // Offset from the last one rather than landing exactly on top of it,
        // where it would be invisible and unclickable on the map.
        b.spawn.push(last
          ? { object: last.object, x: last.x + 80, y: last.y + 80 }
          : { object: 'EPirate06', x: Math.round(m.room.width / 2), y: Math.round(m.room.height / 2) });
        return b.spawn.length - 1;
      },
      removeSpawn(m, i, k) {
        const b = m.beats[i];
        if (!b.spawn || !b.spawn[k]) return false;
        snap(m);
        b.spawn.splice(k, 1);
        // An empty list would write a bare `spawn:` — a key with nothing under
        // it, which reads back as null. The verb is gone, so the key is gone.
        if (!b.spawn.length) delete b.spawn;
        return true;
      },
      // begin() before a typing burst, poke() per keystroke — so undo steps by
      // edit, not by character.
      begin(m) { snap(m); },
      // The dotted-path writer, rooted at a beat. `undefined` deletes — see
      // setPath for why that is the only way to clear an optional look key.
      poke(m, i, path, value) { setPath(m.beats[i], path, value); },
      set(m, i, path, value) { snap(m); Model.poke(m, i, path, value); },
    };
  })();

  return {
    onoff, esc, brk, sayClass, spawnLabel,
    numberBeats, advanceOf, actionsOf, geoOf, stateAt, pingAt, pingAnchors,
    noteLines, noteText, noteFrom, getPath, setPath, LOOK_KEYS,
    lint, drawMap, toYaml, Model, Storm,
  };
})();
