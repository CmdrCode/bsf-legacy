/* EDIT MODEL 3 — COMMAND. The timeline as something you drive, not something you
 * point at. One command line under the transport, modal keys, and a palette for
 * every verb. Built for the case the shipped campaign actually is: twenty-odd
 * beats of dialogue typed in one sitting, where reaching for the mouse between
 * every line is the whole cost. */
window.VARIANTS = window.VARIANTS || {};
window.VARIANTS['3'] = {
  name: 'Command',
  blurb: 'keyboard driven · palette · modal',
  css: TL.css + `
.cmd { display:flex; align-items:center; gap:9px; padding:0 12px; height:30px; border-bottom:1px solid var(--rule-soft); background:#080e0f; }
.cmd .mode { font:9px/1 var(--mono); letter-spacing:.16em; text-transform:uppercase; padding:4px 7px; border-radius:2px;
             background:#132119; color:var(--phos); }
.cmd.edit .mode { background:#2a1f0d; color:var(--amber); }
.cmd .cin { flex:1; background:transparent; border:0; outline:none; color:var(--ink); font:12px/1 var(--mono); padding:6px 0; }
.cmd .cin::placeholder { color:#2f4340; }
.cmd .fieldlbl { font:9px/1 var(--mono); letter-spacing:.12em; text-transform:uppercase; color:var(--amber); }
.cmd .hints { font-size:9.5px; color:#3f5a55; letter-spacing:.06em; white-space:nowrap; }
.cmd .hints b { color:var(--ink-faint); font-weight:400; }
.blk { position:absolute; top:5px; bottom:5px; border:1px solid var(--rule); border-left:2px solid #2f4340;
       background:#0b1214; border-radius:2px; padding:5px 7px; overflow:hidden; cursor:pointer; }
.blk.sel { border-color:var(--phos); border-left-color:var(--phos); background:#0f1a18;
           box-shadow:0 0 0 1px rgba(78,240,138,.25); }
.blk.sel::after { content:''; position:absolute; left:0; top:0; bottom:0; width:2px; background:var(--phos-hot); }
.blk .ic { font-size:9px; color:var(--ink-faint); letter-spacing:2px; }
.blk .wh { font-size:9px; letter-spacing:.1em; text-transform:uppercase; color:var(--phos); margin-top:3px; }
.blk .wh.foe { color:var(--hostile); } .blk .wh.alien { color:var(--alien); } .blk .wh.log { color:var(--log); }
.blk .tx { font-size:10px; color:var(--ink-faint); line-height:1.35; margin-top:2px;
           display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden; }
.blk.sel .tx { color:var(--ink); }
.blk .fno { position:absolute; right:4px; top:4px; font-size:8.5px; color:#2f4340; }
.pal-o { position:fixed; inset:0; z-index:70; background:rgba(4,7,10,.55); display:grid; place-items:start center; padding-top:14vh; }
.pal-o.hide { display:none; }
.pal-b { width:min(560px,86vw); background:#0a1113; border:1px solid var(--rule); border-radius:3px; box-shadow:0 20px 60px rgba(0,0,0,.6); }
.pal-b input { width:100%; background:transparent; border:0; border-bottom:1px solid var(--rule); outline:none;
               color:var(--ink); font:13px/1 var(--mono); padding:12px 14px; }
.pal-l { max-height:46vh; overflow:auto; padding:4px; }
.pal-i { padding:7px 10px; border-radius:2px; font:11.5px/1.3 var(--mono); color:var(--ink-dim); cursor:pointer;
         display:flex; gap:10px; }
.pal-i em { font-style:normal; color:#3f5a55; margin-left:auto; }
.pal-i.on { background:#152021; color:var(--phos); }
.keysheet { position:absolute; right:12px; bottom:14px; font-size:10px; line-height:1.75; color:#3f5a55; pointer-events:none; }
.keysheet b { color:var(--ink-faint); font-weight:400; display:inline-block; min-width:52px; }
`,

  mount(root) {
    const C = Core, M = C.Model;
    const refs = TL.mount(root, { bw: 152, lane: 84 });
    const m = () => App.mission;

    const cmd = document.createElement('div');
    cmd.className = 'cmd';
    cmd.innerHTML = `<span class="mode">normal</span><span class="fieldlbl"></span>
      <input class="cin" placeholder="press ? for keys · enter to edit · : for the palette" readonly>
      <span class="hints"></span>`;
    refs.scroll.parentElement.insertBefore(cmd, refs.scroll);
    const cin = cmd.querySelector('.cin');

    const overlay = document.createElement('div');
    overlay.className = 'pal-o hide';
    overlay.innerHTML = '<div class="pal-b"><input placeholder="type to filter…"><div class="pal-l"></div></div>';
    document.body.appendChild(overlay);
    const pin = overlay.querySelector('input'), plist = overlay.querySelector('.pal-l');

    const sheet = document.createElement('div');
    sheet.className = 'keysheet';
    sheet.innerHTML = `<div><b>← →</b> beat</div><div><b>enter</b> edit field · <b>tab</b> next field</div>
      <div><b>o / O</b> new beat after / before</div><div><b>a / r</b> add / remove action</div>
      <div><b>alt ← →</b> move beat</div><div><b>d</b> duplicate · <b>x</b> delete · <b>u</b> undo</div>
      <div><b>:</b> palette · <b>/</b> find line · <b>space</b> play</div>`;
    refs.cv.parentElement.appendChild(sheet);

    let mode = 'normal', field = 0;

    // ------------------------------------------------------ editable fields
    function fieldsOf(b) {
      const f = [];
      if (b.say) f.push({ p: 'say.text', l: 'say.text' }, { p: 'say.who', l: 'say.who' }, { p: 'say.sprite', l: 'sprite' });
      if (b.objective != null) f.push({ p: 'objective', l: 'objective' });
      if (b.camera) f.push({ p: 'camera.x', l: 'camera.x' }, { p: 'camera.y', l: 'camera.y' }, { p: 'camera.speed', l: 'speed' });
      (b.spawn || []).forEach((_, k) => f.push({ p: `spawn.${k}.object`, l: `spawn${k}.object` },
        { p: `spawn.${k}.x`, l: `spawn${k}.x` }, { p: `spawn.${k}.y`, l: `spawn${k}.y` }));
      if (b.gate != null) f.push({ p: 'gate', l: 'gate index' });
      if (b.music) f.push({ p: 'music', l: 'music' });
      if (b.exec) f.push({ p: 'exec.0', l: 'gml' });
      return f;
    }
    const get = (b, p) => p.split('.').reduce((o, k) => (o == null ? o : o[k]), b);

    // ---------------------------------------------------------------- render
    function renderTrack() {
      const mm = m(), BW = refs.bw;
      refs.beats.innerHTML = mm.beats.map((b, i) => {
        const fs = fieldsOf(b);
        return `<div class="blk${i === App.selected ? ' sel' : ''}" data-i="${i}"
          style="left:${TL.LEFT + i * BW}px;width:${BW - 6}px">${TL.blockInner(b, mm)}
          <span class="fno">${fs.length ? fs.length + 'f' : ''}</span></div>`;
      }).join('');
    }
    function renderCmd() {
      const b = m().beats[App.selected], fs = fieldsOf(b);
      cmd.className = 'cmd ' + (mode === 'edit' ? 'edit' : '');
      cmd.querySelector('.mode').textContent = mode;
      cmd.querySelector('.fieldlbl').textContent = mode === 'edit' && fs[field] ? fs[field].l : '';
      cmd.querySelector('.hints').innerHTML = mode === 'edit'
        ? '<b>enter</b> commit · <b>tab</b> next field · <b>esc</b> cancel'
        : `<b>${fs.length}</b> fields · <b>?</b> keys`;
      if (mode === 'edit' && fs[field]) {
        cin.readOnly = false;
        cin.value = String(get(b, fs[field].p));
        cin.focus(); cin.select();
      } else { cin.readOnly = true; cin.value = ''; cin.blur(); }
    }
    function full() { renderTrack(); renderCmd(); TL.paint(refs); }

    // --------------------------------------------------------- the palette
    let palItems = [], palSel = 0, palDone = null;
    function palette(title, items, done) {
      palItems = items; palSel = 0; palDone = done;
      pin.placeholder = title; pin.value = '';
      overlay.classList.remove('hide');
      drawPal(); pin.focus();
      mode = 'palette'; renderCmd();
    }
    function visible() {
      const q = pin.value.toLowerCase();
      return palItems.filter((it) => (it.label + ' ' + (it.note || '')).toLowerCase().includes(q));
    }
    function drawPal() {
      const vs = visible();
      if (palSel >= vs.length) palSel = Math.max(0, vs.length - 1);
      plist.innerHTML = vs.map((it, i) =>
        `<div class="pal-i${i === palSel ? ' on' : ''}" data-k="${C.esc(it.key)}">${C.esc(it.label)}<em>${C.esc(it.note || '')}</em></div>`).join('');
    }
    function closePal() { overlay.classList.add('hide'); mode = 'normal'; palDone = null; renderCmd(); root.focus(); }
    pin.addEventListener('input', () => { palSel = 0; drawPal(); });
    pin.addEventListener('keydown', (e) => {
      const vs = visible();
      if (e.key === 'Escape') { closePal(); e.preventDefault(); }
      if (e.key === 'ArrowDown') { palSel = Math.min(palSel + 1, vs.length - 1); drawPal(); e.preventDefault(); }
      if (e.key === 'ArrowUp') { palSel = Math.max(palSel - 1, 0); drawPal(); e.preventDefault(); }
      if (e.key === 'Enter' && vs[palSel]) { const d = palDone, k = vs[palSel].key; closePal(); d(k); e.preventDefault(); }
      e.stopPropagation();
    });
    plist.addEventListener('click', (e) => {
      const it = e.target.closest('.pal-i');
      if (it) { const d = palDone; closePal(); d(it.dataset.k); }
    });

    const VERBS = ['say', 'objective', 'spawn', 'gate', 'camera', 'meteors', 'music', 'autosave', 'win', 'empty'];

    // -------------------------------------------------------------- commands
    const CMDS = {
      'insert after': () => palette('new beat after — pick a verb', VERBS.map(v => ({ key: v, label: 'new ' + v + ' beat' })),
        (k) => { App.select(M.insert(m(), App.selected + 1, k)); App.change(); full(); }),
      'insert before': () => palette('new beat before — pick a verb', VERBS.map(v => ({ key: v, label: 'new ' + v + ' beat' })),
        (k) => { App.select(M.insert(m(), App.selected, k)); App.change(); full(); }),
      'add action': () => {
        const b = m().beats[App.selected];
        palette('add an action to this beat', VERBS.filter((v) => v !== 'empty' && !(v in b)).map(v => ({ key: v, label: '+ ' + v })),
          (k) => { const r = M.addAction(m(), App.selected, k); if (!r.ok) TL.toast(refs, r.why); App.change(); full(); });
      },
      'remove action': () => {
        const b = m().beats[App.selected];
        palette('remove an action', Object.keys(b).filter((k) => k !== 'start').map(k => ({ key: k, label: '− ' + k })),
          (k) => { M.removeAction(m(), App.selected, k); App.change(); full(); });
      },
      'duplicate beat': () => { App.select(M.duplicate(m(), App.selected)); App.change(); full(); },
      'delete beat': () => { if (!M.remove(m(), App.selected)) return TL.toast(refs, 'the start beat cannot be deleted'); App.select(Math.min(App.selected, m().beats.length - 1)); App.change(); full(); },
      'move beat left': () => { App.select(M.move(m(), App.selected, App.selected - 1)); App.change(); full(); },
      'move beat right': () => { App.select(M.move(m(), App.selected, App.selected + 1)); App.change(); full(); },
      'undo': () => { if (!M.canUndo()) return TL.toast(refs, 'nothing to undo'); M.undo(m()); App.selected = Math.min(App.selected, m().beats.length - 1); App.change(); full(); },
      'find a line': () => palette('find dialogue',
        m().beats.map((b, i) => ({ key: String(i), label: b.say ? b.say.who + ': ' + b.say.text : (b.objective != null ? 'objective: ' + b.objective : C.actionsOf(b, m()).map(a => a.label).join(' ')), note: 'beat ' + i })),
        (k) => { App.select(+k); full(); }),
      'show yaml': () => { refs.src.classList.toggle('open'); TL.paintSrc(refs); },
    };

    // ------------------------------------------------------------------ keys
    function onKey(e) {
      if (mode === 'palette') return;
      if (mode === 'edit') {
        if (e.key === 'Escape') { mode = 'normal'; renderCmd(); e.preventDefault(); }
        if (e.key === 'Enter' || e.key === 'Tab') {
          const b = m().beats[App.selected], fs = fieldsOf(b), f = fs[field];
          if (f) {
            const cur = get(b, f.p);
            M.begin(m());
            M.poke(m(), App.selected, f.p, typeof cur === 'number' ? Number(cin.value) || 0 : cin.value);
            App.change();
          }
          if (e.key === 'Tab') field = (field + 1) % Math.max(1, fs.length);
          else mode = 'normal';
          full(); e.preventDefault();
        }
        return;
      }
      const k = e.key;
      if (k === 'ArrowRight' && e.altKey) return CMDS['move beat right']() || e.preventDefault();
      if (k === 'ArrowLeft' && e.altKey) return CMDS['move beat left']() || e.preventDefault();
      if (k === 'ArrowRight' || k === 'l') { App.select(App.selected + 1); e.preventDefault(); return; }
      if (k === 'ArrowLeft' || k === 'h') { App.select(App.selected - 1); e.preventDefault(); return; }
      if (k === 'Enter') { field = 0; mode = 'edit'; renderCmd(); e.preventDefault(); return; }
      if (k === 'o') { CMDS['insert after'](); e.preventDefault(); return; }
      if (k === 'O') { CMDS['insert before'](); e.preventDefault(); return; }
      if (k === 'a') { CMDS['add action'](); e.preventDefault(); return; }
      if (k === 'r') { CMDS['remove action'](); e.preventDefault(); return; }
      if (k === 'd') { CMDS['duplicate beat'](); e.preventDefault(); return; }
      if (k === 'x') { CMDS['delete beat'](); e.preventDefault(); return; }
      if (k === 'u') { CMDS['undo'](); e.preventDefault(); return; }
      if (k === '/') { CMDS['find a line'](); e.preventDefault(); return; }
      if (k === ' ') { root.querySelector('[data-t=play]').click(); e.preventDefault(); return; }
      if (k === ':' || (k === 'k' && (e.metaKey || e.ctrlKey))) {
        palette('command', Object.keys(CMDS).map((c) => ({ key: c, label: c })), (c) => CMDS[c]());
        e.preventDefault(); return;
      }
      if (k === '?') { sheet.style.display = sheet.style.display === 'none' ? '' : 'none'; e.preventDefault(); }
    }
    addEventListener('keydown', onKey);
    App.on('unmount', () => { removeEventListener('keydown', onKey); overlay.remove(); });

    refs.beats.addEventListener('click', (e) => {
      const b = e.target.closest('.blk'); if (b) { App.select(+b.dataset.i); full(); }
    });

    App.on('select', () => {
      field = 0;
      refs.beats.querySelectorAll('.blk').forEach((el) => el.classList.toggle('sel', +el.dataset.i === App.selected));
      renderCmd(); TL.paint(refs);
    });
    App.on('change', () => TL.paint(refs));
    new ResizeObserver(() => TL.paint(refs)).observe(refs.cv.parentElement);
    full();
  },
};
