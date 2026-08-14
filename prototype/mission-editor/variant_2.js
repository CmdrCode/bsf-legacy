/* EDIT MODEL 2 — DIRECT. No inspector, no forms, no modal state: the timeline
 * blocks *are* the editor. Type the dialogue where you read it, drag a verb out
 * of the palette onto a block to give that beat an action, drop it in a gap to
 * make a new beat, drag a chip off a block to take the action away, and drag the
 * geometry on the map itself. Everything is where the thing lives. */
window.VARIANTS = window.VARIANTS || {};
window.VARIANTS['2'] = {
  name: 'Direct',
  blurb: 'drag verbs in · type in place',
  css: TL.css + `
.pal { display:flex; align-items:center; gap:5px; padding:5px 12px; border-bottom:1px solid var(--rule-soft);
       background:#080e0f; overflow-x:auto; }
.pal .lbl { font-size:9px; letter-spacing:.14em; text-transform:uppercase; color:#3f5a55; margin-right:4px; }
.pchip { cursor:grab; font:9.5px/1 var(--mono); letter-spacing:.08em; text-transform:uppercase; padding:5px 8px;
         border:1px dashed var(--rule); border-radius:2px; color:var(--ink-dim); white-space:nowrap; user-select:none; }
.pchip:hover { border-color:var(--phos); color:var(--phos); }
.pchip.bin { border-style:solid; border-color:rgba(255,90,77,.35); color:var(--hostile); margin-left:auto; }
.ghost { position:fixed; z-index:80; pointer-events:none; background:#0f1a18; border:1px solid var(--phos);
         color:var(--phos); font:9.5px/1 var(--mono); text-transform:uppercase; padding:5px 8px; border-radius:2px; }
.blk { position:absolute; top:5px; bottom:5px; border:1px solid var(--rule); border-left:2px solid #2f4340;
       background:#0b1214; border-radius:2px; display:flex; flex-direction:column; overflow:hidden; }
.blk.sel { border-color:var(--phos); border-left-color:var(--phos); background:#0f1a18; }
.blk.tgt { border-color:var(--phos-hot); background:#12211d; }
.blk .grip { display:flex; align-items:center; gap:5px; padding:3px 5px; cursor:grab; color:#2f4340; font-size:10px;
             border-bottom:1px solid var(--rule-soft); user-select:none; -webkit-user-select:none; }
.blk .chips, .blk .meta, .pal { user-select:none; -webkit-user-select:none; }
.blk .grip .r { margin-left:auto; color:var(--phos); font-size:9px; }
.blk .chips { display:flex; flex-wrap:wrap; gap:3px; padding:4px 5px 0; }
.chip { cursor:grab; font:8.5px/1 var(--mono); letter-spacing:.06em; text-transform:uppercase; padding:3px 5px;
        border:1px solid var(--rule); border-radius:2px; color:var(--ink-faint); background:#0a1113; white-space:nowrap; }
.chip.say { color:var(--phos); border-color:rgba(78,240,138,.3); }
.chip.objective { color:var(--hostile); border-color:rgba(255,90,77,.3); }
.chip.spawn { color:var(--alien); border-color:rgba(255,92,255,.3); }
.chip.gate { color:var(--phos); }
.blk .body { padding:4px 6px 6px; overflow:auto; }
.blk .who { font:9px/1.3 var(--mono); letter-spacing:.1em; text-transform:uppercase; color:var(--phos); outline:none; }
.blk .who.foe { color:var(--hostile); } .blk .who.alien { color:var(--alien); } .blk .who.log { color:var(--log); }
.blk .txt { font:10.5px/1.45 var(--serif); color:var(--ink-dim); margin-top:3px; outline:none; border-radius:2px; }
.blk.sel .txt { color:var(--ink); }
.blk [contenteditable]:hover { background:#0e1719; }
.blk [contenteditable]:focus { background:#101b1d; box-shadow:inset 0 0 0 1px var(--rule); }
.blk .meta { font:9px/1.4 var(--mono); color:#3f5a55; margin-top:4px; }
.blk .meta b { color:var(--ink-faint); font-weight:400; }
.gap { position:absolute; top:0; bottom:0; width:16px; cursor:pointer; z-index:5; }
.gap::after { content:'+'; position:absolute; inset:0; display:grid; place-items:center; font-size:13px; color:#2f4340; opacity:0; }
.gap:hover::after, .gap.drop::after { opacity:1; color:var(--phos); }
.gap.drop::before { content:''; position:absolute; left:7px; top:2px; bottom:2px; width:2px; background:var(--phos-hot); }
.hint { position:absolute; left:12px; bottom:14px; font-size:10px; color:#2f4340; line-height:1.7; pointer-events:none; }
`,

  mount(root) {
    const C = Core, M = C.Model;
    const VERBS = ['say', 'objective', 'spawn', 'gate', 'camera', 'meteors', 'music', 'autosave', 'win'];
    const refs = TL.mount(root, {
      bw: 196, lane: 214,
      viewExtra: `<div class="hint">drag a beacon, spawn or camera on the map to move it<br>
        chips: drag between beats to move an action, to the bin to delete</div>`,
    });
    const m = () => App.mission;

    // palette above the lanes
    const pal = document.createElement('div');
    pal.className = 'pal';
    pal.innerHTML = '<span class="lbl">verbs</span>' +
      VERBS.map((v) => `<div class="pchip" data-kind="${v}">${v}</div>`).join('') +
      '<div class="pchip bin" data-bin>bin — drop to remove</div>';
    refs.scroll.parentElement.insertBefore(pal, refs.scroll);

    // ------------------------------------------------------------- rendering
    function blockHTML(b, i) {
      const acts = C.actionsOf(b, m());
      const chips = acts.map((a) => `<div class="chip ${a.k}" data-kind="${a.k}" data-i="${i}"
        title="${C.esc(a.label + ' ' + a.detail)}">${a.icon} ${a.k}</div>`).join('');
      const say = b.say;
      let body = '';
      if (say) body = `<div class="who ${C.sayClass(say)}" contenteditable="plaintext-only" data-p="say.who" data-i="${i}">${C.esc(say.who)}</div>
        <div class="txt" contenteditable="plaintext-only" data-p="say.text" data-i="${i}">${C.esc(say.text)}</div>`;
      else if (b.objective != null) body = `<div class="who foe">new objective</div>
        <div class="txt" contenteditable="plaintext-only" data-p="objective" data-i="${i}">${C.esc(b.objective)}</div>`;
      const meta = acts.filter((a) => ['say', 'objective'].indexOf(a.k) < 0)
        .map((a) => `<div><b>${a.label}</b> ${C.esc(a.detail)}</div>`).join('');
      const n = C.numberBeats(m())[i];
      return `<div class="blk${i === App.selected ? ' sel' : ''}" data-i="${i}"
                style="left:${TL.LEFT + i * refs.bw}px;width:${refs.bw - 8}px">
        <div class="grip" data-grip="${i}">⠿ <span>beat ${i}</span><span class="r">${n.n}</span></div>
        <div class="chips">${chips}</div>
        <div class="body">${body}${meta ? `<div class="meta">${meta}</div>` : ''}</div></div>`;
    }

    function renderTrack() {
      const N = m().beats.length;
      const gaps = [];
      for (let i = 1; i <= N; i++) gaps.push(`<div class="gap" data-at="${i}" style="left:${TL.LEFT + i * refs.bw - 12}px"></div>`);
      refs.beats.innerHTML = m().beats.map(blockHTML).join('') + gaps.join('');
    }
    function full() { renderTrack(); TL.paint(refs); }

    // ------------------------------------------------------- text editing
    root.addEventListener('focusin', (e) => { if (e.target.isContentEditable) M.begin(m()); });
    root.addEventListener('input', (e) => {
      const el = e.target; if (!el.dataset || !el.dataset.p) return;
      M.poke(m(), +el.dataset.i, el.dataset.p, el.innerText.replace(/\n/g, ''));
      App.change(); TL.paint(refs);
    });
    root.addEventListener('click', (e) => {
      const blk = e.target.closest('.blk');
      if (blk && !e.target.isContentEditable) App.select(+blk.dataset.i);
      const gap = e.target.closest('.gap');
      if (gap) { App.select(M.insert(m(), +gap.dataset.at, 'say')); App.change(); full(); }
    });

    // --------------------------------------------- dragging chips and blocks
    let drag = null, ghost = null;
    const at = (e) => {
      const el = document.elementFromPoint(e.clientX, e.clientY);
      return {
        blk: el && el.closest('.blk'), gap: el && el.closest('.gap'),
        bin: el && el.closest('[data-bin]'),
      };
    };
    root.addEventListener('pointerdown', (e) => {
      const grip = e.target.closest('[data-grip]');
      const chip = e.target.closest('.chip');
      const pchip = e.target.closest('.pchip:not([data-bin])');
      if (grip) drag = { type: 'block', i: +grip.dataset.grip, label: 'move beat ' + grip.dataset.grip };
      else if (chip) drag = { type: 'chip', kind: chip.dataset.kind, from: +chip.dataset.i, label: chip.dataset.kind };
      else if (pchip) drag = { type: 'chip', kind: pchip.dataset.kind, from: null, label: pchip.dataset.kind };
      else return;
      e.preventDefault();                       // grips and chips are handles
      drag.x0 = e.clientX; drag.y0 = e.clientY;
    });
    const onMove = (e) => {
      if (!drag) return;
      if (!drag.live && Math.hypot(e.clientX - drag.x0, e.clientY - drag.y0) < 6) return;
      if (!drag.live) {
        drag.live = true; TL.drag(true);
        ghost = document.createElement('div'); ghost.className = 'ghost'; ghost.textContent = drag.label;
        document.body.appendChild(ghost);
      }
      ghost.style.left = e.clientX + 10 + 'px'; ghost.style.top = e.clientY + 10 + 'px';
      const t = at(e);
      refs.beats.querySelectorAll('.blk').forEach((b) => b.classList.toggle('tgt', drag.type === 'chip' && b === t.blk));
      refs.beats.querySelectorAll('.gap').forEach((g) => g.classList.toggle('drop', g === t.gap));
      if (drag.type === 'block') {
        const x = e.clientX - refs.scroll.getBoundingClientRect().left + refs.scroll.scrollLeft - TL.LEFT;
        drag.to = Math.max(1, Math.min(m().beats.length, Math.round(x / refs.bw)));
        refs.beats.querySelectorAll('.gap').forEach((g) => g.classList.toggle('drop', +g.dataset.at === drag.to));
      }
    };
    const onUp = (e) => {
      if (!drag || !drag.live) { drag = null; return; }
      TL.drag(false);
      if (ghost) { ghost.remove(); ghost = null; }
      const t = at(e), d = drag; drag = null;
      if (d.type === 'block' && d.to != null) {
        App.select(M.move(m(), d.i, d.to > d.i ? d.to - 1 : d.to));
      } else if (d.type === 'chip') {
        if (t.bin && d.from != null) M.removeAction(m(), d.from, d.kind);
        else if (t.gap) {
          const i = M.insert(m(), +t.gap.dataset.at, d.kind === 'say' ? 'say' : 'empty');
          if (d.kind !== 'say') M.addAction(m(), i, d.kind);
          if (d.from != null) M.removeAction(m(), d.from > i ? d.from + 1 : d.from, d.kind);
          App.select(i);
        } else if (t.blk) {
          const to = +t.blk.dataset.i;
          if (to !== d.from) {
            const r = M.addAction(m(), to, d.kind);
            if (!r.ok) { TL.toast(refs, r.why); full(); return; }
            if (d.from != null) M.removeAction(m(), d.from, d.kind);
            App.select(to);
          }
        } else if (d.from != null) { full(); return; }   // dropped nowhere: no-op
      }
      App.change(); full();
    };
    addEventListener('pointermove', onMove);
    addEventListener('pointerup', onUp);

    // ------------------------------------------------ dragging on the map
    let mdrag = null, tf = null;
    const world = (e) => {
      const r = refs.cv.getBoundingClientRect();
      const W = refs.cv.clientWidth, H = refs.cv.clientHeight, pad = 40;
      const k = Math.min((W - pad * 2) / m().room.width, (H - pad * 2) / m().room.height);
      const ox = (W - m().room.width * k) / 2, oy = (H - m().room.height * k) / 2;
      tf = { k, ox, oy };
      return { x: (e.clientX - r.left - ox) / k, y: (e.clientY - r.top - oy) / k };
    };
    const handles = () => {
      const mm = m(), h = [];
      (mm.gates || []).forEach((g, i) => h.push({ ref: g, beat: mm.beats.findIndex((b) => b.gate === i), what: 'beacon ' + (i + 1) }));
      mm.beats.forEach((b, bi) => {
        (b.spawn || []).forEach((sp) => h.push({ ref: sp, beat: bi, what: sp.object }));
        if (b.camera) h.push({ ref: b.camera, beat: bi, what: 'camera' });
        if (b.gate_at) h.push({ ref: b.gate_at, beat: bi, what: 'gate' });
      });
      h.push({ ref: mm.player, beat: 0, what: mm.player.object });
      return h;
    };
    refs.cv.addEventListener('pointerdown', (e) => {
      const w = world(e);
      let best = null, bd = 30 / tf.k;
      handles().forEach((h) => {
        const d = Math.hypot(h.ref.x - w.x, h.ref.y - w.y);
        if (d < bd) { bd = d; best = h; }
      });
      if (!best) return;
      e.preventDefault(); TL.drag(true);
      M.begin(m()); mdrag = best;
      if (best.beat >= 0) App.select(best.beat);
    });
    refs.cv.addEventListener('pointermove', (e) => {
      const w = world(e);
      if (!mdrag) {
        let hit = false;
        handles().forEach((h) => { if (Math.hypot(h.ref.x - w.x, h.ref.y - w.y) < 30 / tf.k) hit = true; });
        refs.cv.style.cursor = hit ? 'grab' : 'default';
        return;
      }
      mdrag.ref.x = Math.round(w.x); mdrag.ref.y = Math.round(w.y);
      App.dirty = true; TL.paint(refs); renderTrack();
    });
    const onUpMap = () => { if (mdrag) { mdrag = null; TL.drag(false); App.change(); } };
    addEventListener('pointerup', onUpMap);
    App.on('unmount', () => {
      removeEventListener('pointermove', onMove);
      removeEventListener('pointerup', onUp);
      removeEventListener('pointerup', onUpMap);
    });

    App.on('select', () => {
      refs.beats.querySelectorAll('.blk').forEach((el) => el.classList.toggle('sel', +el.dataset.i === App.selected));
      TL.paint(refs);
    });
    App.on('change', () => TL.paint(refs));
    new ResizeObserver(() => TL.paint(refs)).observe(refs.cv.parentElement);
    full();
  },
};
