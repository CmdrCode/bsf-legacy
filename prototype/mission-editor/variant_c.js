/* VARIANT C — Timeline. The map fills the screen and the beats become a
 * transport you scrub. The axis is not seconds, it is the l_messagecount rung —
 * the only clock the runtime has. Things that persist across beats (a gate
 * waiting to be reached, the meteor spawner, music, the always-on fail check)
 * become lanes, so overlaps are visible as overlaps. */
window.VARIANTS = window.VARIANTS || {};
window.VARIANTS.C = {
  name: 'Timeline',
  blurb: 'scrub the mission · lanes show overlap',
  css: `
.tl { display:grid; grid-template-columns:minmax(0,1fr); grid-template-rows:minmax(0,1fr) clamp(250px,34vh,420px);
      height:100vh; width:100vw; overflow:hidden; }
.tl-view { position:relative; min-width:0; min-height:0; }
.tl-panel, .tl-scroll { min-width:0; }
.tl-view canvas { position:absolute; inset:0; width:100%; height:100%; }
.tl-hud { position:absolute; left:12px; top:10px; font-size:10px; color:var(--ink-faint); line-height:1.8; pointer-events:none; }
.tl-hud b { color:var(--phos); font-weight:400; }
.tl-state { position:absolute; right:12px; top:10px; text-align:right; font-size:10px; line-height:1.8; color:var(--ink-faint); pointer-events:none; }
.tl-state em { font-style:normal; color:var(--ink-dim); }
.tl-state .on { color:var(--phos); } .tl-state .off { color:#2f4340; }
/* the in-game message panel, predicted */
.tl-mes { position:absolute; left:50%; transform:translateX(-50%); bottom:16px; width:min(680px,86%);
          display:grid; grid-template-columns:56px 1fr; gap:12px; padding:12px 14px;
          background:rgba(6,12,12,.88); border:1px solid var(--rule); border-radius:2px; }
.tl-mes.hide { display:none; }
.tl-mes .por { width:56px; height:56px; border:1px solid var(--rule); display:grid; place-items:center;
               font-size:8px; color:var(--ink-faint); text-align:center; line-height:1.3; padding:3px; }
.tl-mes .who { font-size:11px; letter-spacing:.16em; text-transform:uppercase; color:var(--phos); }
.tl-mes .who.foe { color:var(--hostile); } .tl-mes .who.alien { color:var(--alien); } .tl-mes .who.log { color:var(--log); }
.tl-mes p { margin:.35rem 0 0; font:14px/1.55 var(--serif); color:var(--ink); }
.tl-panel { border-top:1px solid var(--rule); background:var(--panel); display:grid; grid-template-rows:32px 1fr; min-height:0; }
.tl-tr { display:flex; align-items:center; gap:10px; padding:0 12px; border-bottom:1px solid var(--rule-soft); }
.tl-tr button { all:unset; cursor:pointer; padding:3px 8px; border-radius:2px; color:var(--ink-dim); font-size:12px; }
.tl-tr button:hover { background:#131c1d; color:var(--phos); }
.tl-tr .rd { font-size:10px; color:var(--ink-faint); letter-spacing:.08em; }
.tl-tr .rd b { color:var(--phos); font-weight:400; }
.tl-scroll { overflow-x:auto; overflow-y:hidden; position:relative; }
.tl-track { position:relative; height:100%; }
.tl-lane { position:relative; height:26px; border-bottom:1px solid var(--rule-soft); }
.tl-lane.beats { height:74px; }
.tl-lane .name { position:sticky; left:0; z-index:3; float:left; width:78px; height:100%; background:var(--panel);
                 border-right:1px solid var(--rule-soft); font-size:9px; letter-spacing:.1em; text-transform:uppercase;
                 color:#3f5a55; padding:6px 0 0 8px; }
.tl-cell { position:absolute; top:0; bottom:0; }
.tl-ruler { height:20px; position:relative; border-bottom:1px solid var(--rule); }
.tl-tick { position:absolute; top:0; font-size:9px; color:#2f4340; border-left:1px solid var(--rule-soft); padding:4px 0 0 4px; }
.tl-blk { position:absolute; top:5px; bottom:5px; border:1px solid var(--rule); border-left:2px solid #2f4340;
          background:#0b1214; border-radius:2px; padding:5px 7px; cursor:pointer; overflow:hidden; }
.tl-blk:hover { background:#101a1b; }
.tl-blk.sel { border-color:var(--phos); border-left-color:var(--phos); background:#0f1a18; }
.tl-blk .ic { font-size:9px; color:var(--ink-faint); letter-spacing:2px; }
.tl-blk .wh { font-size:9px; letter-spacing:.1em; text-transform:uppercase; color:var(--phos); margin-top:3px; }
.tl-blk .wh.foe { color:var(--hostile); } .tl-blk .wh.alien { color:var(--alien); } .tl-blk .wh.log { color:var(--log); }
.tl-blk .tx { font-size:10px; color:var(--ink-faint); line-height:1.35; margin-top:2px;
              display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
.tl-span { position:absolute; top:5px; height:16px; border-radius:2px; font-size:9px; letter-spacing:.06em;
           padding:2px 6px; color:#04070a; white-space:nowrap; overflow:hidden; }
.tl-span.gate { background:rgba(78,240,138,.75); }
.tl-span.met { background:rgba(255,182,72,.7); }
.tl-span.mus { background:rgba(120,160,200,.55); }
.tl-span.eer { background:rgba(180,120,200,.5); }
.tl-span.always { background:rgba(255,90,77,.22); color:var(--hostile); border:1px solid rgba(255,90,77,.4); }
.tl-head { position:absolute; top:0; bottom:0; width:1px; background:var(--phos-hot); z-index:4; pointer-events:none; }
.tl-head::before { content:''; position:absolute; top:0; left:-4px; border:4px solid transparent; border-top:6px solid var(--phos-hot); }
`,

  mount(root) {
    const m = App.mission, C = Core;
    const numbered = C.numberBeats(m);
    const BW = 138, LEFT = 78;
    const N = m.beats.length;

    // spans: state that lives across beats, which is what makes lanes worth it
    function spans(pred, cls, label) {
      const out = []; let open = null;
      m.beats.forEach((b, i) => {
        const v = pred(b);
        if (v === 'on' && open == null) open = { i, label: label(b) };
        if (v === 'off' && open != null) { out.push({ a: open.i, b: i, cls, label: open.label }); open = null; }
      });
      if (open != null) out.push({ a: open.i, b: N - 1, cls, label: open.label });
      return out;
    }
    const gateSpans = [];
    m.beats.forEach((b, i) => {
      if (b.gate != null || b.gate_at) {
        const g = b.gate != null ? m.gates[b.gate] : b.gate_at;
        gateSpans.push({ a: i, b: Math.min(i + 1, N - 1), cls: 'gate', label: `MoveToArea (${g.x}, ${g.y})` });
      }
    });
    const metSpans = spans((b) => C.onoff(b.meteors), 'met', () => 'obs_Meteor spawner');
    const musSpans = spans((b) => (b.music ? (b.music === 'stop' ? 'off' : 'on') : null), 'mus', (b) => 'bgm ' + b.music);
    const eerSpans = spans((b) => C.onoff(b.eerie), 'eer', () => 'snd_eeriesound');

    const spanHTML = (s) => `<div class="tl-span ${s.cls}" style="left:${LEFT + s.a * BW + 3}px;width:${(s.b - s.a + 1) * BW - 6}px">${C.esc(s.label)}</div>`;
    const laneHTML = (nm, inner, cls) => `<div class="tl-lane ${cls || ''}"><div class="name">${nm}</div>${inner}</div>`;

    root.innerHTML = `
<div class="tl">
  <div class="tl-view">
    <canvas id="c-cv"></canvas>
    <div class="tl-hud" id="c-hud"></div>
    <div class="tl-state" id="c-st"></div>
    <div class="tl-mes hide" id="c-mes"><div class="por" id="c-por"></div><div><div class="who" id="c-who"></div><p id="c-tx"></p></div></div>
  </div>
  <div class="tl-panel">
    <div class="tl-tr">
      <button id="c-first" title="first beat">⏮</button>
      <button id="c-prev" title="previous">◀</button>
      <button id="c-play" title="play">▶</button>
      <button id="c-next" title="next">▶|</button>
      <button id="c-last" title="last beat">⏭</button>
      <span class="rd">beat <b id="c-i">0</b> / ${N - 1} &nbsp;·&nbsp; l_messagecount <b id="c-n">0</b></span>
      <span class="rd" style="margin-left:auto" id="c-adv"></span>
    </div>
    <div class="tl-scroll" id="c-scroll">
      <div class="tl-track" style="width:${LEFT + N * BW + 40}px">
        <div class="tl-ruler">${numbered.map((e, i) =>
      `<div class="tl-tick" style="left:${LEFT + i * BW}px;width:${BW}px">${e.n}</div>`).join('')}</div>
        ${laneHTML('beats', numbered.map(({ i, beat }) => {
        const acts = C.actionsOf(beat, m), say = beat.say;
        const head = say ? `<div class="wh ${C.sayClass(say)}">${C.esc(say.who)}</div><div class="tx">${C.esc(say.text)}</div>`
          : beat.objective != null ? `<div class="wh foe">objective</div><div class="tx">${C.esc(C.brk(beat.objective).join(' — '))}</div>`
            : `<div class="tx">${C.esc(acts.map((a) => a.label).join(' · ') || '—')}</div>`;
        return `<div class="tl-blk" data-i="${i}" style="left:${LEFT + i * BW}px;width:${BW - 6}px">
                  <div class="ic">${acts.map((a) => a.icon).join('')}</div>${head}</div>`;
      }).join(''), 'beats')}
        ${laneHTML('gates', gateSpans.map(spanHTML).join(''))}
        ${laneHTML('meteors', metSpans.map(spanHTML).join(''))}
        ${laneHTML('music', musSpans.concat(eerSpans).map(spanHTML).join(''))}
        ${laneHTML('always on', `<div class="tl-span always" style="left:${LEFT + 3}px;width:${N * BW - 6}px">
            ship lost → missionFail · ${m.zones.length} storm cells damaging every step</div>`)}
        <div class="tl-head" id="c-head"></div>
      </div>
    </div>
  </div>
</div>`;

    const cv = root.querySelector('#c-cv');
    const scroll = root.querySelector('#c-scroll');
    const blocks = [...root.querySelectorAll('.tl-blk')];

    function paint() {
      const i = App.selected, b = m.beats[i], st = C.stateAt(m, i);
      C.drawMap(cv, { mission: m, reveal: i, focus: b, pad: 40 });
      root.querySelector('#c-hud').innerHTML =
        `<div><b>${C.esc(m.title)}</b> · EP${m.episode}</div>` +
        `<div>beat ${i} · rung ${numbered[i].n} · ${C.actionsOf(b, m).map((a) => a.icon + a.label).join(' ') || 'no actions'}</div>` +
        `<div>camera (${st.camera.x}, ${st.camera.y}) · dashed box = the 1024×768 view</div>`;
      root.querySelector('#c-st').innerHTML =
        `<div><em>beacons</em> ${st.gatesDone.length}/${m.gates.length}</div>` +
        `<div><em>meteors</em> <span class="${st.meteors ? 'on' : 'off'}">${st.meteors ? 'on' : 'off'}</span></div>` +
        `<div><em>eerie</em> <span class="${st.eerie ? 'on' : 'off'}">${st.eerie ? 'on' : 'off'}</span></div>` +
        `<div><em>music</em> ${st.music || '—'}</div>` +
        `<div><em>spawned</em> ${st.spawns.length ? st.spawns.map((s) => s.object).join(', ') : '—'}</div>` +
        `<div><em>autosaves</em> ${st.saves}</div>`;
      const mes = root.querySelector('#c-mes');
      const say = b.say, obj = b.objective;
      if (say || obj != null) {
        mes.classList.remove('hide');
        root.querySelector('#c-who').className = 'who ' + (say ? C.sayClass(say) : 'foe');
        root.querySelector('#c-who').textContent = say ? say.who : 'New Objective';
        root.querySelector('#c-tx').innerHTML = C.brk(say ? say.text : obj).map(C.esc).join('<br>');
        root.querySelector('#c-por').textContent = say ? (say.sprite || 'spr_MesHint') : 'spr_MesObj';
      } else mes.classList.add('hide');
      root.querySelector('#c-i').textContent = i;
      root.querySelector('#c-n').textContent = numbered[i].n;
      const adv = C.advanceOf(b);
      root.querySelector('#c-adv').textContent = adv ? 'advances when: ' + adv.label : '';
      blocks.forEach((el) => el.classList.toggle('sel', +el.dataset.i === i));
      const hx = LEFT + i * BW;
      root.querySelector('#c-head').style.left = hx + 'px';
      if (hx < scroll.scrollLeft + LEFT + 10 || hx > scroll.scrollLeft + scroll.clientWidth - BW)
        scroll.scrollTo({ left: Math.max(0, hx - scroll.clientWidth / 2), behavior: 'smooth' });
    }

    root.addEventListener('click', (e) => {
      const b = e.target.closest('.tl-blk'); if (b) App.select(+b.dataset.i);
    });
    scroll.addEventListener('pointerdown', (e) => {
      if (!e.target.closest('.tl-ruler')) return;
      const scrub = (ev) => {
        const x = ev.clientX - scroll.getBoundingClientRect().left + scroll.scrollLeft - LEFT;
        App.select(Math.round(x / BW));
      };
      scrub(e);
      const up = () => { removeEventListener('pointermove', scrub); removeEventListener('pointerup', up); };
      addEventListener('pointermove', scrub); addEventListener('pointerup', up);
    });

    let timer = null;
    const play = root.querySelector('#c-play');
    play.onclick = () => {
      if (timer) { clearInterval(timer); timer = null; play.textContent = '▶'; return; }
      play.textContent = '❚❚';
      timer = setInterval(() => {
        if (App.selected >= N - 1) { clearInterval(timer); timer = null; play.textContent = '▶'; return; }
        App.select(App.selected + 1);
      }, 1100);
    };
    root.querySelector('#c-first').onclick = () => App.select(0);
    root.querySelector('#c-last').onclick = () => App.select(N - 1);
    root.querySelector('#c-prev').onclick = () => App.select(App.selected - 1);
    root.querySelector('#c-next').onclick = () => App.select(App.selected + 1);

    App.on('select', paint);
    App.on('change', paint);
    new ResizeObserver(paint).observe(cv.parentElement);
    paint();
  },
};
