/* VARIANT A — Workbench. Map is the subject; the beat stack is a sidebar.
 * Primary affordance: drag the mission's geometry. Gates, spawns, storm cells
 * and the player start are draggable handles; the beat that owns whatever you
 * grab selects itself, and its fields open inline in the sidebar. */
window.VARIANTS = window.VARIANTS || {};
window.VARIANTS.A = {
  name: 'Workbench',
  blurb: 'map first · drag the geometry',
  css: `
.wb { display:grid; grid-template-rows:38px 1fr 22px; height:100vh; }
.wb-top { display:flex; align-items:center; gap:14px; padding:0 12px; border-bottom:1px solid var(--rule); background:var(--panel); }
.wb-top h1 { margin:0; font-size:12px; letter-spacing:.14em; text-transform:uppercase; color:var(--log); font-weight:700; }
.wb-top .sub { font-size:11px; color:var(--ink-faint); }
.wb-top .spacer { flex:1; }
.chip { font-size:10px; letter-spacing:.1em; text-transform:uppercase; padding:3px 7px; border:1px solid var(--rule); border-radius:2px; color:var(--ink-faint); }
.chip.ok { color:var(--phos); border-color:rgba(78,240,138,.35); }
.chip.bad { color:var(--hostile); border-color:rgba(255,90,77,.45); }
.chip.dirty { color:var(--amber); border-color:rgba(255,182,72,.45); }
.btn { all:unset; cursor:pointer; font:11px/1 var(--mono); letter-spacing:.08em; text-transform:uppercase;
       padding:6px 10px; border:1px solid var(--rule); border-radius:2px; color:var(--ink-dim); }
.btn:hover { border-color:var(--phos); color:var(--phos); }
.btn.hot { color:var(--amber); border-color:rgba(255,182,72,.4); }
.wb-body { display:grid; grid-template-columns:44px 1fr 384px; min-height:0; }
.wb-rail { border-right:1px solid var(--rule); background:var(--panel); display:flex; flex-direction:column; align-items:center; gap:2px; padding-top:8px; }
.wb-tool { width:30px; height:30px; display:grid; place-items:center; border-radius:2px; color:var(--ink-faint); cursor:pointer; font-size:14px; }
.wb-tool.on, .wb-tool:hover { background:#111a1b; color:var(--phos); }
.wb-map { position:relative; min-width:0; }
.wb-map canvas { position:absolute; inset:0; width:100%; height:100%; }
.wb-hud { position:absolute; left:10px; top:8px; font-size:10px; color:var(--ink-faint); pointer-events:none; line-height:1.7; }
.wb-hud b { color:var(--ink-dim); font-weight:400; }
.wb-legend { position:absolute; right:10px; top:8px; font-size:10px; color:var(--ink-faint); text-align:right; line-height:1.7; pointer-events:none; }
.wb-side { border-left:1px solid var(--rule); display:grid; grid-template-rows:1fr auto; min-height:0; background:var(--panel); }
.wb-stack { overflow:auto; }
.wb-sechead { position:sticky; top:0; background:var(--panel); border-bottom:1px solid var(--rule); padding:7px 10px; font-size:10px; letter-spacing:.16em; text-transform:uppercase; color:var(--phos); z-index:2; }
.wb-row { display:grid; grid-template-columns:30px minmax(0,1fr); gap:9px; padding:7px 10px 5px; cursor:pointer; }
.wb-row:hover { background:#0c1315; }
.wb-row.sel { background:#0f1719; box-shadow:inset 2px 0 0 var(--phos); }
.wb-rung { text-align:right; font-size:10px; color:var(--phos); padding-top:2px; }
.wb-row.sel .wb-rung { color:var(--phos-hot); }
.wb-icons { font-size:10px; color:var(--ink-faint); letter-spacing:3px; }
.wb-who { font-size:10px; letter-spacing:.1em; text-transform:uppercase; color:var(--phos); }
.wb-who.foe { color:var(--hostile); } .wb-who.alien { color:var(--alien); } .wb-who.log { color:var(--log); }
.wb-line { font-size:11.5px; color:var(--ink-dim); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.wb-row.sel .wb-line { white-space:normal; color:var(--ink); }
.wb-adv { display:grid; grid-template-columns:30px 1fr; gap:9px; padding:0 10px 6px; font-size:9.5px; color:var(--ink-faint); }
.wb-adv i { font-style:normal; color:#2b3a38; }
.wb-adv.gate span { color:var(--phos); }
.wb-form { grid-column:2; display:grid; grid-template-columns:auto 1fr; gap:4px 8px; align-items:center; margin:6px 0 4px; }
.wb-form label { font-size:9.5px; letter-spacing:.1em; text-transform:uppercase; color:var(--ink-faint); }
.wb-form input, .wb-form textarea { font:11px/1.45 var(--mono); background:#0a1113; color:var(--ink); border:1px solid var(--rule); border-radius:2px; padding:4px 6px; width:100%; }
.wb-form input:focus, .wb-form textarea:focus { outline:none; border-color:var(--phos); }
.wb-form .xy { display:flex; gap:6px; }
.wb-always { border-top:1px solid var(--rule); background:#080d0e; max-height:34%; overflow:auto; }
.wb-al { padding:6px 10px; border-bottom:1px solid var(--rule-soft); }
.wb-al b { display:block; font-size:10px; letter-spacing:.1em; text-transform:uppercase; color:var(--hostile); font-weight:400; }
.wb-al .when { font-size:9.5px; color:var(--ink-faint); }
.wb-al p { margin:2px 0 0; font-size:10.5px; color:var(--ink-dim); }
.wb-status { display:flex; align-items:center; gap:16px; padding:0 12px; border-top:1px solid var(--rule); background:var(--panel); font-size:10px; color:var(--ink-faint); }
.wb-status .k { color:var(--ink-dim); }
`,

  mount(root) {
    const m = App.mission, C = Core;
    const numbered = C.numberBeats(m);
    root.innerHTML = `
<div class="wb">
  <header class="wb-top">
    <h1>EP${m.episode} · ${C.esc(m.title)}</h1>
    <span class="sub">${m.room.width}×${m.room.height} · global.mission ${m.mission} · ${m.beats.length} beats</span>
    <span class="spacer"></span>
    <span class="chip" id="a-lint"></span><span class="chip" id="a-dirty" hidden>unbuilt</span>
    <button class="btn" id="a-build">build</button>
    <button class="btn hot" id="a-poke">poke game →</button>
  </header>
  <div class="wb-body">
    <div class="wb-rail">
      ${['↖ select', '◇ gate', '◆ spawn', '◉ zone', '▣ camera', '✦ meteor'].map((t, i) =>
      `<div class="wb-tool${i ? '' : ' on'}" title="${t.slice(2)}">${t[0]}</div>`).join('')}
    </div>
    <div class="wb-map">
      <canvas id="a-cv"></canvas>
      <div class="wb-hud" id="a-hud"></div>
      <div class="wb-legend">
        <div><span style="color:var(--phos)">◇</span> gates &nbsp; <span style="color:var(--alien)">□</span> spawns</div>
        <div><span style="color:var(--hostile)">○</span> storm cells &nbsp; <span style="color:var(--ink)">⌗</span> 1024×768 view</div>
        <div>drag any handle to move it</div>
      </div>
    </div>
    <aside class="wb-side">
      <div class="wb-stack"><div class="wb-sechead">beats — ladder on l_messagecount</div><div id="a-rows"></div></div>
      <div class="wb-always">
        <div class="wb-sechead" style="color:var(--hostile)">always watching</div>
        ${C.alwaysOn(m).map((a) => `<div class="wb-al"><b>${a.title}</b>
          <span class="when">${a.when}</span><p>${C.esc(a.detail)}</p></div>`).join('')}
      </div>
    </aside>
  </div>
  <footer class="wb-status">
    <span><span class="k">room</span> ${m.room.width}×${m.room.height}</span>
    <span><span class="k">player</span> ${m.player.object} @ <i id="a-pxy"></i></span>
    <span><span class="k">scenery</span> ter_Nebula ×${(m.scenery || {}).nebula || 0}</span>
    <span><span class="k">cursor</span> <i id="a-cur">—</i></span>
    <span style="margin-left:auto" id="a-sel"></span>
  </footer>
</div>`;

    const cv = root.querySelector('#a-cv');
    const rowsEl = root.querySelector('#a-rows');
    let tf = null, hits = [];

    function handles() {
      const h = [{ kind: 'player', x: m.player.x, y: m.player.y, beat: 0, ref: m.player, label: m.player.object }];
      (m.gates || []).forEach((g, i) => {
        const bi = m.beats.findIndex((b) => b.gate === i);
        h.push({ kind: 'gate', x: g.x, y: g.y, beat: bi < 0 ? 0 : bi, ref: g, label: 'beacon ' + (i + 1) });
      });
      m.beats.forEach((b, bi) => {
        (b.spawn || []).forEach((sp) => h.push({ kind: 'spawn', x: sp.x, y: sp.y, beat: bi, ref: sp, label: sp.object }));
        if (b.gate_at) h.push({ kind: 'gate', x: b.gate_at.x, y: b.gate_at.y, beat: bi, ref: b.gate_at, label: 'ad-hoc gate' });
        if (b.camera) h.push({ kind: 'camera', x: b.camera.x, y: b.camera.y, beat: bi, ref: b.camera, label: 'camera' });
      });
      (m.zones || []).forEach((z, i) => h.push({ kind: 'zone', x: z.x, y: z.y, beat: -1, ref: z, label: 'storm ' + (i + 1) }));
      return h;
    }

    function draw() {
      tf = C.drawMap(cv, { mission: m, focus: m.beats[App.selected], pad: 26 });
      hits = handles();
      root.querySelector('#a-hud').innerHTML =
        `<div><b>beat ${App.selected}</b> of ${m.beats.length - 1} selected</div>` +
        `<div>${C.actionsOf(m.beats[App.selected], m).map((a) => a.icon + ' ' + a.label).join(' · ') || 'no actions'}</div>`;
      root.querySelector('#a-pxy').textContent = `(${m.player.x}, ${m.player.y})`;
      const errs = C.lint(m), lc = root.querySelector('#a-lint');
      lc.textContent = errs.length ? errs.length + ' lint errors' : 'lint clean';
      lc.className = 'chip ' + (errs.length ? 'bad' : 'ok');
      root.querySelector('#a-dirty').hidden = !App.dirty;
      root.querySelector('#a-dirty').className = 'chip dirty';
    }

    function rowHTML(entry) {
      const { n, i, beat } = entry;
      const acts = C.actionsOf(beat, m);
      const say = beat.say;
      const sel = i === App.selected;
      const head = say
        ? `<div class="wb-who ${C.sayClass(say)}">${C.esc(say.who)}</div><div class="wb-line">${C.esc(say.text)}</div>`
        : beat.objective != null
          ? `<div class="wb-who foe">new objective</div><div class="wb-line">${C.esc(C.brk(beat.objective).join(' — '))}</div>`
          : `<div class="wb-line" style="color:var(--ink-faint)">${acts.map((a) => a.label + ' ' + a.detail).join(' · ') || '—'}</div>`;
      const adv = C.advanceOf(beat);
      return `<div class="wb-row${sel ? ' sel' : ''}" data-i="${i}">
        <div class="wb-rung">${n}</div>
        <div>
          <div class="wb-icons">${acts.map((a) => a.icon).join('')}</div>
          ${head}
          ${sel ? formHTML(beat) : ''}
        </div>
      </div>
      ${adv ? `<div class="wb-adv ${adv.kind}"><i>│</i><div>↓ <span>${adv.label}</span>${adv.sub ? ' · ' + adv.sub : ''}</div></div>` : ''}`;
    }

    function formHTML(b) {
      const f = [];
      if (b.say) {
        f.push(`<label>who</label><input data-f="say.who" value="${C.esc(b.say.who)}">`);
        f.push(`<label>sprite</label><input data-f="say.sprite" value="${C.esc(b.say.sprite || 'spr_MesHint')}">`);
        f.push(`<label>text</label><textarea data-f="say.text" rows="4">${C.esc(b.say.text)}</textarea>`);
      }
      if (b.objective != null) f.push(`<label>objective</label><textarea data-f="objective" rows="2">${C.esc(b.objective)}</textarea>`);
      if (b.camera) f.push(`<label>camera</label><div class="xy">
          <input data-f="camera.x" value="${b.camera.x}"><input data-f="camera.y" value="${b.camera.y}">
          <input data-f="camera.speed" value="${b.camera.speed == null ? 60 : b.camera.speed}" title="speed"></div>`);
      if (b.gate != null) f.push(`<label>gate</label><input data-f="gate" value="${b.gate}">`);
      (b.spawn || []).forEach((sp, k) => f.push(`<label>spawn ${k}</label><div class="xy">
          <input data-f="spawn.${k}.object" value="${C.esc(sp.object)}">
          <input data-f="spawn.${k}.x" value="${sp.x}" style="max-width:70px">
          <input data-f="spawn.${k}.y" value="${sp.y}" style="max-width:70px"></div>`));
      return f.length ? `<div class="wb-form">${f.join('')}</div>` : '';
    }

    function renderRows() {
      rowsEl.innerHTML = numbered.map(rowHTML).join('');
      root.querySelector('#a-sel').textContent =
        `beat ${App.selected} · rung ${numbered[App.selected].n}`;
      const sel = rowsEl.querySelector('.wb-row.sel');
      if (sel) sel.scrollIntoView({ block: 'nearest' });
    }

    rowsEl.addEventListener('click', (e) => {
      const r = e.target.closest('.wb-row');
      if (r && !e.target.closest('.wb-form')) App.select(+r.dataset.i);
    });
    rowsEl.addEventListener('input', (e) => {
      const f = e.target.dataset.f; if (!f) return;
      const b = m.beats[App.selected], parts = f.split('.');
      let v = e.target.value;
      if (/^(x|y|speed|gate)$/.test(parts[parts.length - 1])) v = Number(v) || 0;
      if (parts[0] === 'spawn') b.spawn[+parts[1]][parts[2]] = v;
      else if (parts.length === 2) b[parts[0]][parts[1]] = v;
      else b[parts[0]] = v;
      App.change(); draw();
    });

    // ---- dragging handles on the map
    let drag = null;
    const world = (e) => {
      const r = cv.getBoundingClientRect();
      return { x: (e.clientX - r.left - tf.ox) / tf.k, y: (e.clientY - r.top - tf.oy) / tf.k };
    };
    const near = (w) => {
      let best = null, bd = 26 / tf.k;
      hits.forEach((h) => {
        const d = Math.hypot(h.x - w.x, h.y - w.y);
        if (d < bd) { bd = d; best = h; }
      });
      return best;
    };
    cv.addEventListener('pointerdown', (e) => {
      const w = world(e), h = near(w);
      if (!h) return;
      e.preventDefault();                       // dragging a handle, not selecting
      drag = h;
      try { cv.setPointerCapture(e.pointerId); } catch (_) { /* synthetic events */ }
      if (h.beat >= 0) App.select(h.beat);
    });
    cv.addEventListener('pointermove', (e) => {
      const w = world(e);
      root.querySelector('#a-cur').textContent = `${Math.round(w.x)}, ${Math.round(w.y)}`;
      if (drag) {
        drag.ref.x = Math.round(w.x); drag.ref.y = Math.round(w.y);
        App.dirty = true; draw();
        if (drag.beat === App.selected) renderRows();
      } else {
        cv.style.cursor = near(w) ? 'grab' : 'default';
      }
    });
    cv.addEventListener('pointerup', () => { if (drag) { drag = null; App.change(); } });

    root.querySelector('#a-build').onclick = function () {
      this.textContent = 'build.py → mods/act2m1.gml ✓'; App.dirty = false; draw();
      setTimeout(() => (this.textContent = 'build'), 1600);
    };
    root.querySelector('#a-poke').onclick = function () {
      this.textContent = 'wrote mods/mission 8 …'; setTimeout(() => (this.textContent = 'poke game →'), 1600);
    };

    App.on('select', () => { renderRows(); draw(); });
    App.on('change', draw);
    new ResizeObserver(() => draw()).observe(cv.parentElement);
    renderRows(); draw();
  },
};
