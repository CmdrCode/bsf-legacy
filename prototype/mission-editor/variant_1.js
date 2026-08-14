/* EDIT MODEL 1 — INSPECTOR. The NLE answer: the timeline is the arrangement,
 * a docked rail is the detail. Blocks stay compact and read-only; select one and
 * every verb it carries becomes a card of fields you can edit, remove, or add to.
 * Structure is edited on the track (drag to reorder, + in the gaps to insert),
 * content is edited in the rail. Nothing is edited in two places. */
window.VARIANTS = window.VARIANTS || {};
window.VARIANTS['1'] = {
  name: 'Inspector',
  blurb: 'compact track · docked field rail',
  css: TL.css + `
/* The rail takes its space out of the map rather than covering it. Never
   width:auto on a canvas — it is a replaced element, so auto resolves to the
   backing-store width that drawMap itself sets from clientWidth, and the two
   feed each other until the map is twice the window. */
.tl-view canvas { right:346px; width:calc(100% - 346px); }
.tl-state { right:358px; }
.tl-mes { left:calc(50% - 173px); }
.ins { position:absolute; right:0; top:0; bottom:0; width:346px; background:rgba(8,13,14,.94);
       border-left:1px solid var(--rule); display:grid; grid-template-rows:auto 1fr auto; }
.ins-h { padding:9px 12px; border-bottom:1px solid var(--rule); }
.ins-h .n { font-size:10px; letter-spacing:.16em; text-transform:uppercase; color:var(--phos); }
.ins-h .a { font-size:10px; color:var(--ink-faint); margin-top:2px; }
.ins-b { overflow:auto; padding:8px 12px; }
.card { border:1px solid var(--rule); border-left:2px solid var(--rule); border-radius:2px; margin-bottom:7px; background:#0a1012; }
.card.say { border-left-color:var(--phos); } .card.objective { border-left-color:var(--hostile); }
.card.spawn { border-left-color:var(--alien); } .card.gate { border-left-color:var(--phos); }
.card.camera, .card.ping { border-left-color:#7aa0c8; } .card.exec { border-left-color:var(--amber); }
.card > h5 { margin:0; padding:5px 8px; font:9.5px/1 var(--mono); letter-spacing:.14em; text-transform:uppercase;
             color:var(--ink-faint); display:flex; justify-content:space-between; border-bottom:1px solid var(--rule-soft); }
.card > h5 .x { cursor:pointer; color:#3f5a55; }
.card > h5 .x:hover { color:var(--hostile); }
.card .rows { padding:6px 8px; display:grid; grid-template-columns:auto minmax(0,1fr); gap:4px 8px; align-items:center; }
.card label { font-size:9px; letter-spacing:.1em; text-transform:uppercase; color:#3f5a55; }
.card input, .card select, .card textarea { font:11px/1.45 var(--mono); background:#070d0e; color:var(--ink);
  border:1px solid var(--rule); border-radius:2px; padding:3px 5px; width:100%; }
.card input:focus, .card textarea:focus, .card select:focus { outline:none; border-color:var(--phos); }
.card .xy { display:flex; gap:5px; }
.ins-add { display:flex; flex-wrap:wrap; gap:4px; margin-top:8px; }
.ins-add button, .ins-f button { all:unset; cursor:pointer; font:9.5px/1 var(--mono); letter-spacing:.08em;
  text-transform:uppercase; padding:5px 7px; border:1px solid var(--rule); border-radius:2px; color:var(--ink-dim); }
.ins-add button:hover, .ins-f button:hover { border-color:var(--phos); color:var(--phos); }
.ins-f { display:flex; gap:4px; padding:8px 12px; border-top:1px solid var(--rule); }
.ins-f button.del:hover { border-color:var(--hostile); color:var(--hostile); }
/* the track */
.blk { position:absolute; top:5px; bottom:5px; border:1px solid var(--rule); border-left:2px solid #2f4340;
       background:#0b1214; border-radius:2px; padding:5px 7px; cursor:grab; overflow:hidden;
       user-select:none; -webkit-user-select:none; }
.spr, .sprgrid, .menu { user-select:none; -webkit-user-select:none; }
.blk:hover { background:#101a1b; }
.blk.sel { border-color:var(--phos); border-left-color:var(--phos); background:#0f1a18; }
.blk.drag { opacity:.35; }
.blk .ic { font-size:9px; color:var(--ink-faint); letter-spacing:2px; }
.blk .wh { font-size:9px; letter-spacing:.1em; text-transform:uppercase; color:var(--phos); margin-top:3px; }
.blk .wh.foe { color:var(--hostile); } .blk .wh.alien { color:var(--alien); } .blk .wh.log { color:var(--log); }
.blk .tx { font-size:10px; color:var(--ink-faint); line-height:1.35; margin-top:2px;
           display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden; }
.gap { position:absolute; top:0; bottom:0; width:14px; cursor:pointer; z-index:5; }
.gap::after { content:'+'; position:absolute; inset:0; display:grid; place-items:center; font-size:13px;
              color:#2f4340; opacity:0; transition:opacity .12s; }
.gap:hover::after { opacity:1; color:var(--phos); }
.gap.drop::before { content:''; position:absolute; left:6px; top:2px; bottom:2px; width:2px; background:var(--phos-hot); }
/* real art: the portrait a say will actually show, and the sprite a spawn will
   actually be — pulled from the exe, so a wrong resource name is visibly wrong */
.spr { display:flex; align-items:center; gap:8px; cursor:pointer; padding:3px; border:1px solid transparent; border-radius:2px; }
.spr:hover { border-color:var(--rule); background:#0c1416; }
.spr .thumb { width:46px; height:46px; flex:none; border:1px solid var(--rule); background:#050a0b;
              display:grid; place-items:center; overflow:hidden; }
.spr .thumb img { max-width:100%; max-height:100%; image-rendering:pixelated; }
.spr .thumb.miss { color:var(--hostile); font-size:8px; text-align:center; }
.spr .nm { font-size:10.5px; color:var(--ink); }
.spr .dim { font-size:9px; color:#3f5a55; }
.sprgrid { position:fixed; z-index:75; background:#0b1214; border:1px solid var(--rule); border-radius:3px;
           padding:8px; display:grid; grid-template-columns:repeat(4,74px); gap:6px; max-height:60vh; overflow:auto;
           box-shadow:0 16px 44px rgba(0,0,0,.6); }
.sprgrid figure { margin:0; cursor:pointer; text-align:center; border:1px solid transparent; border-radius:2px; padding:3px; }
.sprgrid figure:hover, .sprgrid figure.on { border-color:var(--phos); background:#101a18; }
.sprgrid img { width:56px; height:56px; object-fit:contain; image-rendering:pixelated; display:block; margin:0 auto; }
.sprgrid figcaption { font-size:8px; color:var(--ink-faint); margin-top:3px; word-break:break-all; }
.menu { position:fixed; z-index:70; background:#0b1214; border:1px solid var(--rule); border-radius:2px; padding:3px; }
.menu button { all:unset; display:block; cursor:pointer; font:10px/1 var(--mono); padding:6px 10px; color:var(--ink-dim); border-radius:2px; }
.menu button:hover { background:#152021; color:var(--phos); }
`,

  mount(root) {
    const m0 = App.mission, C = Core, M = C.Model;
    const refs = TL.mount(root, {
      bw: 152, lane: 84,
      viewExtra: `<aside class="ins"><div class="ins-h"></div><div class="ins-b"></div><div class="ins-f">
        <button data-op="before">+ before</button><button data-op="after">+ after</button>
        <button data-op="dup">duplicate</button><button data-op="undo">undo</button>
        <button data-op="del" class="del">delete</button></div></aside>`,
    });
    const m = () => App.mission;

    // ---------------------------------------------------------------- track
    function renderTrack() {
      const mm = m(), N = mm.beats.length, BW = refs.bw;
      const blocks = mm.beats.map((b, i) =>
        `<div class="blk" data-i="${i}" style="left:${TL.LEFT + i * BW}px;width:${BW - 6}px">${TL.blockInner(b, mm)}</div>`);
      const gaps = [];
      for (let i = 1; i <= N; i++) gaps.push(`<div class="gap" data-at="${i}" style="left:${TL.LEFT + i * BW - 10}px"></div>`);
      refs.beats.innerHTML = blocks.join('') + gaps.join('');
      refs.beats.querySelectorAll('.blk').forEach((el) => el.classList.toggle('sel', +el.dataset.i === App.selected));
    }

    // ------------------------------------------------------------ inspector
    // a sprite field, shown as the sprite: the portrait the GUI_Messager will
    // draw, with its real size and origin, or a red MISSING when the name is not
    // in the tree (which is exactly what build.py's lint would reject)
    function sprField(path, name, filter) {
      const A = window.Assets, s = A && A.ok ? A.sprites[name] : null;
      const thumb = !A || !A.ok
        ? `<div class="thumb dim">no art</div>`
        : s ? `<div class="thumb"><img src="api/sprite/${encodeURIComponent(name)}?f=0" alt=""></div>`
          : `<div class="thumb miss">not in tree</div>`;
      return `<div class="spr" data-pick="${path}" data-filter="${filter}">${thumb}
        <div><div class="nm">${C.esc(name)}</div>
        <div class="dim">${s ? `${s.w}×${s.h} · origin ${s.ox},${s.oy}${s.n > 1 ? ' · ' + s.n + ' frames' : ''}` : 'click to pick'}</div></div></div>`;
    }

    // what a spawned object will look like: its own sprite_index, tinted the way
    // its Create event tints it (masks would otherwise draw as black boxes)
    function objPreview(obj) {
      const A = window.Assets;
      if (!A || !A.ok) return '<span class="dim" style="font-size:9px">no art</span>';
      const nm = A.spriteOf(obj);
      const s = nm && A.sprites[nm];
      return `<div class="spr">${s
        ? `<div class="thumb"><img src="api/sprite/${encodeURIComponent(nm)}?f=0" alt=""></div>`
        : '<div class="thumb miss">unknown object</div>'}
        <div><div class="nm">${C.esc(nm || obj)}</div>
        <div class="dim">${s ? `${s.w}×${s.h}${s.mask ? ' · palette mask' : ''}` : 'not in objects_rt'}</div></div></div>`;
    }

    const F = {
      say: (b) => [
        ['who', `<input data-p="say.who" value="${C.esc(b.say.who)}">`],
        ['portrait', sprField('say.sprite', b.say.sprite || 'spr_MesHint', '^spr_Mes')],
        ['colour', sel('say.color', b.say.color || 'green', ['green', 'red', 'magenta', 'white'])],
        ['text', `<textarea data-p="say.text" rows="5">${C.esc(b.say.text)}</textarea>`],
      ],
      objective: (b) => [['text', `<textarea data-p="objective" rows="3">${C.esc(b.objective)}</textarea>`]],
      camera: (b) => [['x / y', `<div class="xy"><input data-p="camera.x" data-num value="${b.camera.x}">
        <input data-p="camera.y" data-num value="${b.camera.y}"></div>`],
      ['speed', `<input data-p="camera.speed" data-num value="${b.camera.speed == null ? 60 : b.camera.speed}">`]],
      spawn: (b) => b.spawn.flatMap((sp, k) => [
        [`#${k}`, `<div class="xy">
          <input data-p="spawn.${k}.object" value="${C.esc(sp.object)}">
          <input data-p="spawn.${k}.x" data-num value="${sp.x}" style="max-width:62px">
          <input data-p="spawn.${k}.y" data-num value="${sp.y}" style="max-width:62px"></div>`],
        ['', objPreview(sp.object)],
      ]),
      gate: (b) => [['beacon', sel('gate', b.gate, (m().gates || []).map((g, k) => k), (k) => `${+k + 1} — (${m().gates[k].x}, ${m().gates[k].y})`)],
      ['wait', sel('wait', b.wait || 'none', ['gate', 'none'])]],
      gate_at: (b) => [['x / y', `<div class="xy"><input data-p="gate_at.x" data-num value="${b.gate_at.x}">
        <input data-p="gate_at.y" data-num value="${b.gate_at.y}"></div>`]],
      ping: (b) => [['x / y', `<div class="xy"><input data-p="ping.0" data-num value="${b.ping[0]}">
        <input data-p="ping.1" data-num value="${b.ping[1]}"></div>`]],
      music: (b) => [['track', sel('music', b.music, ['stop', 'theme', 'battle'])]],
      eerie: (b) => [['state', sel('eerie', C.onoff(b.eerie), ['on', 'off'])]],
      meteors: (b) => [['spawner', sel('meteors', C.onoff(b.meteors), ['on', 'off'])]],
      exec: (b) => [['gml', `<textarea data-p="exec.0" rows="3">${C.esc(b.exec[0] || '')}</textarea>`]],
      autosave: () => [['', '<span style="font-size:10px;color:var(--ink-faint)">saveGame() unless difficulty = Hard</span>']],
      win: () => [['', '<span style="font-size:10px;color:var(--ink-faint)">missionSucc() — ends the episode</span>']],
      start: () => [['', '<span style="font-size:10px;color:var(--ink-faint)">runs from alarm[2], counter stays 0</span>']],
      wait: () => [],
    };
    function sel(path, cur, opts, label) {
      return `<select data-p="${path}">` + opts.map((o) =>
        `<option value="${o}"${String(o) === String(cur) ? ' selected' : ''}>${C.esc(label ? label(o) : o)}</option>`).join('') + '</select>';
    }

    const ADDABLE = ['say', 'objective', 'spawn', 'gate', 'camera', 'meteors', 'music', 'autosave', 'win'];

    function renderIns() {
      const mm = m(), i = App.selected, b = mm.beats[i];
      const n = C.numberBeats(mm)[i], adv = C.advanceOf(b);
      root.querySelector('.ins-h').innerHTML =
        `<div class="n">beat ${i} · rung ${n.n}</div><div class="a">↓ ${adv ? adv.label : '—'}${adv && adv.sub ? ' · ' + adv.sub : ''}</div>`;
      const cards = Object.keys(b).filter((k) => F[k] && (k !== 'wait')).map((k) => {
        const rows = F[k](b).map(([l, html]) => `<label>${l}</label><div>${html}</div>`).join('');
        return `<div class="card ${k}"><h5>${k}${k === 'start' ? '' : `<span class="x" data-rm="${k}">✕</span>`}</h5>
          ${rows ? `<div class="rows">${rows}</div>` : ''}</div>`;
      }).join('');
      const add = ADDABLE.filter((k) => !(k in b)).map((k) => `<button data-add="${k}">+ ${k}</button>`).join('');
      root.querySelector('.ins-b').innerHTML = cards + `<div class="ins-add">${add}</div>`;
    }

    function full() { renderTrack(); renderIns(); TL.paint(refs); }

    // ------------------------------------------------------------- wiring
    root.addEventListener('focusin', (e) => { if (e.target.matches('input,textarea')) M.begin(m()); });
    root.addEventListener('input', (e) => {
      const p = e.target.dataset.p; if (!p) return;
      let v = e.target.value;
      if (e.target.dataset.num != null) v = Number(v) || 0;
      if (p === 'gate') v = Number(v);
      if (p === 'wait') { if (v === 'none') delete m().beats[App.selected].wait; else M.poke(m(), App.selected, 'wait', 'gate'); }
      else if (p === 'eerie' || p === 'meteors') M.poke(m(), App.selected, p, v === 'on');
      else M.poke(m(), App.selected, p, v);
      App.change(); renderTrack(); TL.paint(refs);
    });
    root.addEventListener('change', (e) => { if (e.target.matches('select')) { M.begin(m()); renderIns(); } });

    // ---- the sprite picker: every matching sprite in the tree, as itself
    function spritePicker(x, y, current, filter, cb) {
      const A = window.Assets;
      if (!A || !A.ok) return TL.toast(refs, 'no game art — start run.py with the game available');
      const re = new RegExp(filter);
      const names = Object.keys(A.sprites).filter((n) => re.test(n)).sort();
      const el = document.createElement('div');
      el.className = 'sprgrid';
      el.style.left = Math.min(x, innerWidth - 330) + 'px';
      el.style.top = Math.min(y, innerHeight - 340) + 'px';
      el.innerHTML = names.map((n) => `<figure class="${n === current ? 'on' : ''}" data-n="${n}">
        <img src="api/sprite/${encodeURIComponent(n)}?f=0" alt="" loading="lazy">
        <figcaption>${n.replace(/^spr_/, '')}</figcaption></figure>`).join('')
        || '<div class="dim">nothing matches</div>';
      document.body.appendChild(el);
      el.addEventListener('click', (ev) => {
        const f = ev.target.closest('figure');
        if (f) { el.remove(); cb(f.dataset.n); }
      });
      setTimeout(() => addEventListener('pointerdown', function off(ev) {
        if (!el.contains(ev.target)) { el.remove(); removeEventListener('pointerdown', off); }
      }), 0);
    }

    root.addEventListener('click', (e) => {
      const pick = e.target.closest('[data-pick]');
      if (pick) {
        const path = pick.dataset.pick;
        const cur = path.split('.').reduce((o, k) => o[k], m().beats[App.selected]);
        const r = pick.getBoundingClientRect();
        return spritePicker(r.left - 300, r.bottom + 4, cur, pick.dataset.filter,
          (n) => { M.set(m(), App.selected, path, n); App.change(); full(); });
      }
      const blk = e.target.closest('.blk');
      if (blk) return App.select(+blk.dataset.i);
      const gap = e.target.closest('.gap');
      if (gap) return kindMenu(e.clientX, e.clientY, (kind) => { App.select(M.insert(m(), +gap.dataset.at, kind)); App.change(); full(); });
      const rm = e.target.dataset.rm;
      if (rm) { M.removeAction(m(), App.selected, rm); App.change(); full(); return; }
      const add = e.target.dataset.add;
      if (add) {
        const r = M.addAction(m(), App.selected, add);
        if (!r.ok) return TL.toast(refs, r.why);
        App.change(); full(); return;
      }
      const op = e.target.dataset.op;
      if (op) {
        const i = App.selected;
        if (op === 'before') App.select(M.insert(m(), i, 'say'));
        if (op === 'after') App.select(M.insert(m(), i + 1, 'say'));
        if (op === 'dup') App.select(M.duplicate(m(), i));
        if (op === 'del') { if (!M.remove(m(), i)) return TL.toast(refs, 'the start beat cannot be deleted'); App.select(Math.min(i, m().beats.length - 1)); }
        if (op === 'undo') { if (!M.canUndo()) return TL.toast(refs, 'nothing to undo'); M.undo(m()); App.selected = Math.min(App.selected, m().beats.length - 1); }
        App.change(); full();
      }
    });

    function kindMenu(x, y, cb) {
      const el = document.createElement('div');
      el.className = 'menu';
      el.style.left = Math.min(x, innerWidth - 140) + 'px';
      el.style.top = Math.min(y, innerHeight - 240) + 'px';
      el.innerHTML = ['say', 'objective', 'spawn', 'gate', 'camera', 'empty']
        .map((k) => `<button data-k="${k}">new ${k} beat</button>`).join('');
      document.body.appendChild(el);
      el.addEventListener('click', (ev) => { const k = ev.target.dataset.k; if (k) { el.remove(); cb(k); } });
      setTimeout(() => addEventListener('pointerdown', function off(ev) {
        if (!el.contains(ev.target)) { el.remove(); removeEventListener('pointerdown', off); }
      }), 0);
    }

    // ---- drag a block to reorder
    let drag = null;
    refs.beats.addEventListener('pointerdown', (e) => {
      const blk = e.target.closest('.blk'); if (!blk) return;
      e.preventDefault();                       // a block is a handle, not text
      drag = { i: +blk.dataset.i, x0: e.clientX, el: blk, live: false };
    });
    const onMove = (e) => {
      if (!drag) return;
      if (!drag.live && Math.abs(e.clientX - drag.x0) < 6) return;
      if (!drag.live) TL.drag(true);
      drag.live = true; drag.el.classList.add('drag');
      const x = e.clientX - refs.scroll.getBoundingClientRect().left + refs.scroll.scrollLeft - TL.LEFT;
      drag.to = Math.max(1, Math.min(m().beats.length, Math.round(x / refs.bw)));
      refs.beats.querySelectorAll('.gap').forEach((g) => g.classList.toggle('drop', +g.dataset.at === drag.to));
    };
    const onUp = () => {
      if (drag && drag.live && drag.to != null) {
        const to = drag.to > drag.i ? drag.to - 1 : drag.to;
        App.select(M.move(m(), drag.i, to)); App.change(); full();
      }
      if (drag && drag.live) TL.drag(false);
      drag = null;
    };
    addEventListener('pointermove', onMove);
    addEventListener('pointerup', onUp);
    App.on('unmount', () => {
      removeEventListener('pointermove', onMove); removeEventListener('pointerup', onUp);
    });

    App.on('select', () => {
      refs.beats.querySelectorAll('.blk').forEach((el) => el.classList.toggle('sel', +el.dataset.i === App.selected));
      renderIns(); TL.paint(refs);
    });
    App.on('change', () => TL.paint(refs));
    new ResizeObserver(() => TL.paint(refs)).observe(refs.cv.parentElement);
    void m0; full();
  },
};
