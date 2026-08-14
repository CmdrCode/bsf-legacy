/* Shared TIMELINE CHROME — the shape that won round one (variant C).
 *
 * Round two is about editing, so the chrome is deliberately shared: map on top,
 * transport, ruler, and one lane per thing that persists across beats. What the
 * three editing variants own is the *beats lane* (refs.beats) and whatever
 * editing surface they add — that is the only place they are allowed to differ.
 */
window.TL = (function () {
  'use strict';
  const C = Core;

  const css = `
/* min-width:0 everywhere a grid item holds the scrolling track: without it the
   track's 3700px min-content width widens the whole grid and the map canvas
   silently becomes twice the window, drawing the room half off-screen. */
.tl { display:grid; grid-template-columns:minmax(0,1fr); grid-template-rows:minmax(0,1fr) auto;
      height:100vh; width:100vw; overflow:hidden; --bw:150px; --lane:78px; }
.tl-view { position:relative; min-width:0; min-height:0; }
.tl-panel, .tl-scroll { min-width:0; }
.tl-view canvas { position:absolute; inset:0; width:100%; height:100%; }
.tl-hud { position:absolute; left:12px; top:10px; font-size:10px; color:var(--ink-faint); line-height:1.8; pointer-events:none; }
.tl-hud b { color:var(--phos); font-weight:400; }
.tl-state { position:absolute; right:12px; top:10px; text-align:right; font-size:10px; line-height:1.8; color:var(--ink-faint); pointer-events:none; }
.tl-state em { font-style:normal; color:var(--ink-dim); }
.tl-state .on { color:var(--phos); } .tl-state .off { color:#2f4340; }
.tl-mes { position:absolute; left:50%; transform:translateX(-50%); bottom:16px; width:min(660px,80%);
          display:grid; grid-template-columns:52px 1fr; gap:12px; padding:11px 13px;
          background:rgba(6,12,12,.88); border:1px solid var(--rule); border-radius:2px; }
.tl-mes.hide { display:none; }
.tl-mes .por { width:52px; height:52px; border:1px solid var(--rule); display:grid; place-items:center;
               font-size:8px; color:var(--ink-faint); text-align:center; line-height:1.3; padding:3px;
               overflow:hidden; }
.tl-mes .por img { width:100%; height:100%; object-fit:contain; image-rendering:pixelated; }
.tl-mes .who { font-size:11px; letter-spacing:.16em; text-transform:uppercase; color:var(--phos); }
.tl-mes .who.foe { color:var(--hostile); } .tl-mes .who.alien { color:var(--alien); } .tl-mes .who.log { color:var(--log); }
.tl-mes p { margin:.3rem 0 0; font:14px/1.55 var(--serif); color:var(--ink); }
.tl-panel { border-top:1px solid var(--rule); background:var(--panel); display:grid; grid-template-rows:32px auto; min-height:0; }
.tl-tr { display:flex; align-items:center; gap:8px; padding:0 12px; border-bottom:1px solid var(--rule-soft); }
.tl-tr button { all:unset; cursor:pointer; padding:3px 8px; border-radius:2px; color:var(--ink-dim); font-size:12px; }
.tl-tr button:hover { background:#131c1d; color:var(--phos); }
.tl-tr .rd { font-size:10px; color:var(--ink-faint); letter-spacing:.08em; }
.tl-tr .rd b { color:var(--phos); font-weight:400; }
.tl-tr .sep { width:1px; height:16px; background:var(--rule); }
.tl-chip { font-size:9.5px; letter-spacing:.1em; text-transform:uppercase; padding:2px 6px;
           border:1px solid var(--rule); border-radius:2px; color:var(--ink-faint); }
.tl-chip.ok { color:var(--phos); border-color:rgba(78,240,138,.35); }
.tl-chip.bad { color:var(--hostile); border-color:rgba(255,90,77,.45); }
.tl-chip.dirty { color:var(--amber); border-color:rgba(255,182,72,.45); }
.tl-scroll { overflow-x:auto; overflow-y:hidden; position:relative; }
.tl-track { position:relative; }
.tl-lane { position:relative; height:26px; border-bottom:1px solid var(--rule-soft); }
.tl-lane.beats { height:var(--lane); }
.tl-lane > .name { position:sticky; left:0; z-index:3; float:left; width:74px; height:100%; background:var(--panel);
                 border-right:1px solid var(--rule-soft); font-size:9px; letter-spacing:.1em; text-transform:uppercase;
                 color:#3f5a55; padding:6px 0 0 8px; }
.tl-ruler { height:20px; position:relative; border-bottom:1px solid var(--rule); }
.tl-tick { position:absolute; top:0; font-size:9px; color:#2f4340; border-left:1px solid var(--rule-soft); padding:4px 0 0 4px; }
.tl-tick.sel { color:var(--phos-hot); }
.tl-span { position:absolute; top:5px; height:16px; border-radius:2px; font-size:9px; letter-spacing:.06em;
           padding:2px 6px; color:#04070a; white-space:nowrap; overflow:hidden; }
.tl-span.gate { background:rgba(78,240,138,.75); }
.tl-span.met { background:rgba(255,182,72,.7); }
.tl-span.mus { background:rgba(120,160,200,.55); }
.tl-span.eer { background:rgba(180,120,200,.5); }
.tl-span.always { background:rgba(255,90,77,.22); color:var(--hostile); border:1px solid rgba(255,90,77,.4); }
.tl-head { position:absolute; top:0; bottom:0; width:1px; background:var(--phos-hot); z-index:4; pointer-events:none; }
.tl-head::before { content:''; position:absolute; top:0; left:-4px; border:4px solid transparent; border-top:6px solid var(--phos-hot); }
/* Dragging must never turn into a text selection. Everything on the track and
   in the transport is chrome you grab, not prose you select — except the fields
   the variants make editable, which opt back in. */
.tl-tr, .tl-ruler, .tl-lane, .tl-view { user-select:none; -webkit-user-select:none; }
[contenteditable], input, textarea { user-select:text; -webkit-user-select:text; }
img { -webkit-user-drag:none; user-select:none; }
body.tl-dragging { cursor:grabbing !important; }
body.tl-dragging *, body.tl-dragging [contenteditable] { user-select:none !important; -webkit-user-select:none !important; }
/* the source drawer — proof that whatever you do on the timeline comes back out as the DSL */
.tl-src { position:fixed; right:0; bottom:0; top:0; width:520px; background:#050a0b; border-left:1px solid var(--rule);
          z-index:50; display:grid; grid-template-rows:32px 1fr; transform:translateX(100%); transition:transform .18s ease; }
.tl-src.open { transform:none; }
.tl-src h4 { margin:0; padding:9px 12px; font:10px/1 var(--mono); letter-spacing:.16em; text-transform:uppercase;
             color:var(--ink-faint); border-bottom:1px solid var(--rule); }
.tl-src h4 span { float:right; color:#2f4340; }
.tl-src pre { margin:0; overflow:auto; padding:10px 12px 30vh; font:11px/1.5 var(--mono); color:var(--ink-dim); white-space:pre; }
.tl-src .hl { color:var(--phos); }
.tl-toast { position:fixed; left:50%; bottom:64px; transform:translateX(-50%); z-index:60; padding:7px 12px;
            background:#1b1113; border:1px solid rgba(255,90,77,.5); color:var(--hostile); border-radius:2px;
            font-size:11px; opacity:0; transition:opacity .15s; pointer-events:none; }
.tl-toast.on { opacity:1; }
`;

  const LEFT = 74;

  function spansOf(m) {
    const N = m.beats.length;
    const run = (pred, cls, label) => {
      const out = []; let open = null;
      m.beats.forEach((b, i) => {
        const v = pred(b);
        if (v === 'on' && open == null) open = { i, label: label(b) };
        if (v === 'off' && open != null) { out.push({ a: open.i, b: i, cls, label: open.label }); open = null; }
      });
      if (open != null) out.push({ a: open.i, b: N - 1, cls, label: open.label });
      return out;
    };
    const gates = [];
    m.beats.forEach((b, i) => {
      if (b.gate != null || b.gate_at) {
        const g = b.gate != null ? m.gates[b.gate] : b.gate_at;
        if (g) gates.push({ a: i, b: Math.min(i + 1, N - 1), cls: 'gate', label: `MoveToArea (${g.x}, ${g.y})` });
      }
    });
    return {
      gates,
      met: run((b) => C.onoff(b.meteors), 'met', () => 'obs_Meteor spawner'),
      mus: run((b) => (b.music ? (b.music === 'stop' ? 'off' : 'on') : null), 'mus', (b) => 'bgm ' + b.music),
      eer: run((b) => C.onoff(b.eerie), 'eer', () => 'snd_eeriesound'),
    };
  }

  /* Build the chrome. `opts.transportExtra` is html dropped into the transport
     bar; `opts.viewExtra` is html dropped over the map (inspector rails etc). */
  function mount(root, opts) {
    opts = opts || {};
    root.innerHTML = `
<div class="tl" style="--bw:${opts.bw || 150}px;--lane:${opts.lane || 78}px">
  <div class="tl-view">
    <canvas class="tl-cv"></canvas>
    <div class="tl-hud"></div>
    <div class="tl-state"></div>
    <div class="tl-mes hide"><div class="por"></div><div><div class="who"></div><p></p></div></div>
    ${opts.viewExtra || ''}
  </div>
  <div class="tl-panel">
    <div class="tl-tr">
      <button data-t="first" title="first beat">⏮</button>
      <button data-t="prev" title="previous">◀</button>
      <button data-t="play" title="play">▶</button>
      <button data-t="next" title="next">▶|</button>
      <button data-t="last" title="last beat">⏭</button>
      <span class="rd">beat <b class="rd-i">0</b> / <span class="rd-n"></span> · l_messagecount <b class="rd-r">0</b></span>
      <span class="sep"></span>
      <span class="tl-chip lintchip"></span>
      <span class="tl-chip dirty dirtychip" hidden>edited</span>
      <span class="tl-chip artchip" title="sprites are pulled out of the exe in memory"></span>
      ${opts.transportExtra || ''}
      <span class="rd advrd" style="margin-left:auto"></span>
      <button data-t="src" title="show the YAML this would save">{ } yaml</button>
    </div>
    <div class="tl-scroll">
      <div class="tl-track">
        <div class="tl-ruler"></div>
        <div class="tl-lane beats"><div class="name">beats</div><div class="beatslane"></div></div>
        <div class="tl-lane"><div class="name">gates</div><div class="lane-gates"></div></div>
        <div class="tl-lane"><div class="name">meteors</div><div class="lane-met"></div></div>
        <div class="tl-lane"><div class="name">music</div><div class="lane-mus"></div></div>
        <div class="tl-lane"><div class="name">always on</div><div class="lane-always"></div></div>
        <div class="tl-head"></div>
      </div>
    </div>
  </div>
</div>
<div class="tl-src"><h4>campaign/missions/ep9.yaml <span>Core.toYaml(model) · not written to disk</span></h4><pre></pre></div>
<div class="tl-toast"></div>`;

    const $ = (s) => root.querySelector(s);
    const refs = {
      root, bw: opts.bw || 150, LEFT,
      cv: $('.tl-cv'), hud: $('.tl-hud'), state: $('.tl-state'), mes: $('.tl-mes'),
      scroll: $('.tl-scroll'), track: $('.tl-track'), beats: $('.beatslane'),
      ruler: $('.tl-ruler'), head: $('.tl-head'), src: $('.tl-src'), toast: $('.tl-toast'),
    };

    // transport
    let timer = null;
    const playBtn = root.querySelector('[data-t=play]');
    root.querySelectorAll('.tl-tr button').forEach((b) => (b.onclick = () => {
      const t = b.dataset.t, N = App.mission.beats.length;
      if (t === 'first') App.select(0);
      if (t === 'last') App.select(N - 1);
      if (t === 'prev') App.select(App.selected - 1);
      if (t === 'next') App.select(App.selected + 1);
      if (t === 'src') { refs.src.classList.toggle('open'); paintSrc(refs); }
      if (t === 'play') {
        if (timer) { clearInterval(timer); timer = null; playBtn.textContent = '▶'; return; }
        playBtn.textContent = '❚❚';
        timer = setInterval(() => {
          if (App.selected >= App.mission.beats.length - 1) { clearInterval(timer); timer = null; playBtn.textContent = '▶'; return; }
          App.select(App.selected + 1);
        }, 1100);
      }
    }));

    // scrubbing on the ruler
    refs.ruler.addEventListener('pointerdown', (e) => {
      e.preventDefault();                       // no caret, no selection
      drag(true);
      const scrub = (ev) => {
        const x = ev.clientX - refs.scroll.getBoundingClientRect().left + refs.scroll.scrollLeft - LEFT;
        App.select(Math.round(x / refs.bw));
      };
      scrub(e);
      const up = () => {
        drag(false);
        removeEventListener('pointermove', scrub); removeEventListener('pointerup', up);
      };
      addEventListener('pointermove', scrub); addEventListener('pointerup', up);
    });

    return refs;
  }

  /* Held for the whole of any drag: kills selection and pins the cursor. */
  function drag(on) {
    document.body.classList.toggle('tl-dragging', !!on);
    if (!on) {
      const s = getSelection();
      if (s && s.isCollapsed === false && !document.activeElement.isContentEditable) s.removeAllRanges();
    }
  }

  function toast(refs, msg) {
    refs.toast.textContent = msg;
    refs.toast.classList.add('on');
    clearTimeout(refs._tt);
    refs._tt = setTimeout(() => refs.toast.classList.remove('on'), 2200);
  }

  function paintSrc(refs) {
    if (!refs.src.classList.contains('open')) return;
    const y = Core.toYaml(App.mission).split('\n');
    // mark the selected beat's block so edits are traceable in the source
    let bi = -1, start = y.findIndex((l) => l === 'beats:');
    const out = y.map((l, i) => {
      if (i > start && /^  - /.test(l)) bi++;
      const t = Core.esc(l);
      return i > start && bi === App.selected ? `<span class="hl">${t}</span>` : t;
    });
    refs.src.querySelector('pre').innerHTML = out.join('\n');
  }

  /* Everything that is not the beats lane: map, readouts, spans, playhead. */
  function paint(refs) {
    const m = App.mission, i = App.selected, b = m.beats[i], N = m.beats.length;
    const numbered = C.numberBeats(m), st = C.stateAt(m, i);
    const BW = refs.bw;

    C.drawMap(refs.cv, { mission: m, reveal: i, focus: b, pad: 40 });

    refs.hud.innerHTML =
      `<div><b>${C.esc(m.title)}</b> · EP${m.episode} · ${N} beats</div>` +
      `<div>beat ${i} · rung ${numbered[i].n} · ${C.actionsOf(b, m).map((a) => a.icon + a.label).join(' ') || 'no actions'}</div>` +
      `<div>camera (${st.camera.x}, ${st.camera.y}) · dashed box = the 1024×768 view</div>`;
    refs.state.innerHTML =
      `<div><em>beacons</em> ${st.gatesDone.length}/${(m.gates || []).length}</div>` +
      `<div><em>meteors</em> <span class="${st.meteors ? 'on' : 'off'}">${st.meteors ? 'on' : 'off'}</span></div>` +
      `<div><em>eerie</em> <span class="${st.eerie ? 'on' : 'off'}">${st.eerie ? 'on' : 'off'}</span></div>` +
      `<div><em>music</em> ${st.music || '—'}</div>` +
      `<div><em>spawned</em> ${st.spawns.length ? st.spawns.map((s) => s.object).join(', ') : '—'}</div>`;

    const say = b.say, obj = b.objective;
    if (say || obj != null) {
      refs.mes.classList.remove('hide');
      refs.mes.querySelector('.who').className = 'who ' + (say ? C.sayClass(say) : 'foe');
      refs.mes.querySelector('.who').textContent = say ? say.who : 'New Objective';
      refs.mes.querySelector('p').innerHTML = C.brk(say ? say.text : obj).map(C.esc).join('<br>') || '<i>—</i>';
      const spr = say ? (say.sprite || 'spr_MesHint') : 'spr_MesObj';
      const por = refs.mes.querySelector('.por');
      por.innerHTML = window.Assets && Assets.ok && Assets.sprites[spr]
        ? `<img src="api/sprite/${encodeURIComponent(spr)}?f=0" alt="${spr}">`
        : C.esc(spr);
    } else refs.mes.classList.add('hide');

    refs.root.querySelector('.rd-i').textContent = i;
    refs.root.querySelector('.rd-n').textContent = N - 1;
    refs.root.querySelector('.rd-r').textContent = numbered[i].n;
    const adv = C.advanceOf(b);
    refs.root.querySelector('.advrd').textContent = adv ? 'advances when: ' + adv.label : '';
    const errs = C.lint(m), lc = refs.root.querySelector('.lintchip');
    lc.textContent = errs.length ? errs.length + ' lint' : 'lint clean';
    lc.className = 'tl-chip lintchip ' + (errs.length ? 'bad' : 'ok');
    refs.root.querySelector('.dirtychip').hidden = !App.dirty;
    const ac = refs.root.querySelector('.artchip'), art = window.Assets;
    ac.textContent = art && art.ok ? `art · ${Object.keys(art.sprites).length} sprites` : 'no art';
    ac.className = 'tl-chip artchip ' + (art && art.ok ? 'ok' : '');

    // ruler + spans + track width
    const W = refs.LEFT + N * BW + 40;
    refs.track.style.width = W + 'px';
    refs.ruler.innerHTML = numbered.map((e, k) =>
      `<div class="tl-tick${k === i ? ' sel' : ''}" style="left:${refs.LEFT + k * BW}px;width:${BW}px">${e.n}</div>`).join('');
    const sp = spansOf(m);
    const html = (s) => `<div class="tl-span ${s.cls}" style="left:${refs.LEFT + s.a * BW + 3}px;width:${(s.b - s.a + 1) * BW - 6}px">${C.esc(s.label)}</div>`;
    refs.root.querySelector('.lane-gates').innerHTML = sp.gates.map(html).join('');
    refs.root.querySelector('.lane-met').innerHTML = sp.met.map(html).join('');
    refs.root.querySelector('.lane-mus').innerHTML = sp.mus.concat(sp.eer).map(html).join('');
    refs.root.querySelector('.lane-always').innerHTML =
      `<div class="tl-span always" style="left:${refs.LEFT + 3}px;width:${N * BW - 6}px">ship lost → missionFail · ${(m.zones || []).length} storm cells damaging every step</div>`;

    const hx = refs.LEFT + i * BW;
    refs.head.style.left = hx + 'px';
    if (hx < refs.scroll.scrollLeft + refs.LEFT + 10 || hx > refs.scroll.scrollLeft + refs.scroll.clientWidth - BW)
      refs.scroll.scrollTo({ left: Math.max(0, hx - refs.scroll.clientWidth / 2), behavior: 'smooth' });
    paintSrc(refs);
  }

  // block content shared by the variants that show a compact card
  function blockInner(b, m) {
    const acts = C.actionsOf(b, m), say = b.say;
    const head = say
      ? `<div class="wh ${C.sayClass(say)}">${C.esc(say.who)}</div><div class="tx">${C.esc(say.text)}</div>`
      : b.objective != null
        ? `<div class="wh foe">objective</div><div class="tx">${C.esc(C.brk(b.objective).join(' — '))}</div>`
        : `<div class="tx">${C.esc(acts.map((a) => a.label).join(' · ') || 'empty beat')}</div>`;
    return `<div class="ic">${acts.map((a) => a.icon).join('')}</div>${head}`;
  }

  return { css, mount, paint, paintSrc, toast, spansOf, blockInner, drag, LEFT };
})();
