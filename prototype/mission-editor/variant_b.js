/* VARIANT B — Script. The mission read and written as a shooting script: one
 * reading column, dialogue set like a screenplay, actions as stage directions.
 * Primary affordance: type. Every line of dialogue is editable in place; the
 * map is demoted to a small sticky panel that follows whatever you are reading. */
window.VARIANTS = window.VARIANTS || {};
window.VARIANTS.B = {
  name: 'Script',
  blurb: 'writer first · edit dialogue in place',
  css: `
.sc-doc { height:100vh; overflow:auto; scroll-behavior:smooth; }
.sc-col { max-width:47rem; margin:0 auto; padding:3rem 1.5rem 40vh; }
.sc-front { border-bottom:1px solid var(--rule); padding-bottom:1.6rem; margin-bottom:2rem; }
.sc-eyebrow { font-size:10px; letter-spacing:.24em; text-transform:uppercase; color:var(--phos); }
.sc-front h1 { font:400 2.4rem/1.15 var(--serif); color:var(--log); margin:.5rem 0 .2rem; letter-spacing:-.01em; }
.sc-front .sub { font-size:11px; letter-spacing:.14em; text-transform:uppercase; color:var(--ink-faint); }
.sc-meta { display:flex; flex-wrap:wrap; gap:.4rem 1.6rem; margin-top:1.2rem; font-size:11px; color:var(--ink-faint); }
.sc-meta b { color:var(--ink-dim); font-weight:400; }
.sc-cast { margin-top:1.1rem; display:flex; flex-wrap:wrap; gap:.5rem; }
.sc-cast span { font-size:10px; letter-spacing:.1em; text-transform:uppercase; border:1px solid var(--rule); border-radius:999px; padding:3px 9px; color:var(--ink-dim); }
.sc-beat { position:relative; padding:.2rem 0 .2rem 3.2rem; }
.sc-beat .rung { position:absolute; left:0; top:.35rem; width:2.2rem; text-align:right; font-size:10px; color:#2f4340; }
.sc-beat.act .rung { color:var(--phos); }
.sc-beat.act { background:linear-gradient(90deg,rgba(78,240,138,.045),transparent 70%); }
.sc-dir { font:italic 13px/1.7 var(--serif); color:var(--ink-faint); margin:.15rem 0; }
.sc-dir b { font-style:normal; font-family:var(--mono); font-size:10px; letter-spacing:.1em; text-transform:uppercase; color:#3f5a55; margin-right:.5em; font-weight:400; }
.sc-say { margin:1.1rem 0 1.2rem; }
.sc-who { font:11px/1 var(--mono); letter-spacing:.18em; text-transform:uppercase; color:var(--phos); margin-left:6.5rem; }
.sc-who.foe { color:var(--hostile); } .sc-who.alien { color:var(--alien); } .sc-who.log { color:var(--log); }
.sc-who .spr { color:#2f4340; letter-spacing:.06em; margin-left:.8em; }
.sc-text { font:17px/1.62 var(--serif); color:var(--ink); margin:.32rem 0 0 3.2rem; max-width:34rem; padding:.15rem .4rem; border-radius:2px; outline:none; }
.sc-text:hover { background:#0b1113; }
.sc-text .brk { color:#2f4340; }
.sc-text:focus { background:#0d1517; box-shadow:inset 0 0 0 1px var(--rule); }
.sc-obj { margin:1.2rem 0 1.2rem 3.2rem; border-left:2px solid var(--hostile); background:rgba(255,90,77,.06); padding:.6rem .9rem; max-width:34rem; }
.sc-obj .lbl { font:10px/1 var(--mono); letter-spacing:.18em; text-transform:uppercase; color:var(--hostile); }
.sc-obj .sc-text { margin:.35rem 0 0; font-size:15px; }
.sc-conn { display:flex; align-items:center; gap:.7rem; margin:0 0 0 3.2rem; padding:.5rem 0; color:#2b3a38; }
.sc-conn .bar { width:1px; height:1.5rem; background:#1d2a2a; }
.sc-conn .lab { font-size:10px; letter-spacing:.08em; color:var(--ink-faint); }
.sc-conn.gate .lab { color:var(--phos); }
.sc-conn.end .lab { color:var(--amber); }
.sc-end { margin:2rem 0 0 3.2rem; font:11px/1 var(--mono); letter-spacing:.2em; text-transform:uppercase; color:var(--amber); }

.sc-side { position:fixed; right:calc(50% - 47rem/2 - 20rem); top:3rem; width:17rem; }
@media (max-width:1500px) { .sc-side { right:1.2rem; } }
@media (max-width:1180px) { .sc-side { display:none; } }
.sc-card { border:1px solid var(--rule); background:var(--panel); border-radius:2px; margin-bottom:.8rem; }
.sc-card h3 { font:10px/1 var(--mono); letter-spacing:.16em; text-transform:uppercase; color:var(--ink-faint); margin:0; padding:8px 10px; border-bottom:1px solid var(--rule-soft); }
.sc-card canvas { display:block; width:100%; height:11rem; }
.sc-card .body { padding:8px 10px; font-size:10.5px; color:var(--ink-dim); line-height:1.7; }
.sc-card .body i { color:var(--ink-faint); font-style:normal; }
.sc-cue { display:flex; justify-content:space-between; }
.sc-cue span:last-child { color:var(--ink); }
.sc-watch { position:fixed; left:calc(50% - 47rem/2 - 15rem); top:3rem; width:13rem; }
@media (max-width:1500px) { .sc-watch { left:1.2rem; } }
@media (max-width:1180px) { .sc-watch { display:none; } }
.sc-note { border-left:2px solid rgba(255,90,77,.5); padding:.2rem 0 .2rem .7rem; margin-bottom:1rem; }
.sc-note b { display:block; font:10px/1.4 var(--mono); letter-spacing:.12em; text-transform:uppercase; color:var(--hostile); font-weight:400; }
.sc-note p { margin:.25rem 0 0; font-size:10.5px; line-height:1.6; color:var(--ink-faint); }
.sc-hint { position:fixed; left:0; right:0; bottom:52px; text-align:center; font-size:10px; color:#2f4340; pointer-events:none; }
`,

  mount(root) {
    const m = App.mission, C = Core;
    const numbered = C.numberBeats(m);
    const cast = [...new Set(m.beats.filter((b) => b.say).map((b) => b.say.who))];

    // '#' is the game's line break; keep it in the text but let it recede
    const body = (s) => C.esc(s).split('#').join('<span class="brk">#</span>');

    const dirs = (b) => C.actionsOf(b, m)
      .filter((a) => ['say', 'objective'].indexOf(a.k) < 0)
      .map((a) => `<p class="sc-dir"><b>${a.label}</b>${C.esc(a.detail)}</p>`).join('');

    const beatHTML = ({ n, i, beat }) => {
      const adv = C.advanceOf(beat);
      const say = beat.say;
      return `<div class="sc-beat" data-i="${i}"><div class="rung">${n}</div>
        ${dirs(beat)}
        ${beat.objective != null ? `<div class="sc-obj"><div class="lbl">new objective</div>
           <div class="sc-text" contenteditable="plaintext-only" data-i="${i}" data-f="objective">${body(beat.objective)}</div></div>` : ''}
        ${say ? `<div class="sc-say"><div class="sc-who ${C.sayClass(say)}">${C.esc(say.who)}
             <span class="spr">${C.esc(say.sprite || 'spr_MesHint')}</span></div>
           <div class="sc-text" contenteditable="plaintext-only" data-i="${i}" data-f="say.text">${body(say.text)}</div></div>` : ''}
      </div>
      ${adv && adv.kind !== 'end'
          ? `<div class="sc-conn ${adv.kind}"><div class="bar"></div><div class="lab">${adv.label}</div></div>`
          : adv ? '<div class="sc-end">— mission accomplished —</div>' : ''}`;
    };

    root.innerHTML = `
<div class="sc-doc" id="b-doc">
  <div class="sc-col">
    <div class="sc-front">
      <div class="sc-eyebrow">Act II · Episode ${m.episode} · beat script</div>
      <h1>${C.esc(m.title)}</h1>
      <div class="sub">${C.esc(m.subtitle)} · answers to global.mission ${m.mission}</div>
      <div class="sc-meta">
        <span><b>room</b> ${m.room.width}×${m.room.height}</span>
        <span><b>player</b> ${m.player.object} at (${m.player.x}, ${m.player.y}), hull ×${m.player.damage}</span>
        <span><b>beats</b> ${m.beats.length}</span>
        <span><b>fail</b> ${C.esc(C.brk(m.fail.ship).join(' / '))}</span>
      </div>
      <div class="sc-cast">${cast.map((c) => `<span>${C.esc(c)}</span>`).join('')}</div>
    </div>
    ${numbered.map(beatHTML).join('')}
  </div>
</div>
<div class="sc-watch">
  <div class="sc-eyebrow" style="margin-bottom:.8rem">always watching</div>
  ${C.alwaysOn(m).map((a) => `<div class="sc-note"><b>${a.title}</b><p>${C.esc(a.detail)}</p></div>`).join('')}
</div>
<aside class="sc-side">
  <div class="sc-card"><h3 id="b-maph">where we are</h3><canvas id="b-cv"></canvas></div>
  <div class="sc-card"><h3>cue sheet</h3><div class="body" id="b-cue"></div></div>
</aside>
<div class="sc-hint">click any line to rewrite it · # is a line break · ↑↓ moves the read-head</div>`;

    const cv = root.querySelector('#b-cv');
    const doc = root.querySelector('#b-doc');
    const beats = [...root.querySelectorAll('.sc-beat')];

    function paint() {
      const i = App.selected, st = C.stateAt(m, i);
      C.drawMap(cv, { mission: m, reveal: i, focus: m.beats[i], pad: 10, labels: false });
      root.querySelector('#b-maph').textContent =
        `beat ${i} · ${st.activeGate ? 'heading for beacon ' + (st.activeGate.idx + 1) : 'no gate open'}`;
      const cue = [
        ['music', st.music || '—'], ['ambience', st.eerie ? 'eerie loop' : 'silent'],
        ['meteors', st.meteors ? 'spawning' : 'off'], ['camera', `(${st.camera.x}, ${st.camera.y})`],
        ['beacons', `${st.gatesDone.length}/${m.gates.length} reached`],
        ['autosaves', st.saves], ['objective', st.objective ? C.brk(st.objective)[0] : '—'],
      ];
      root.querySelector('#b-cue').innerHTML = cue
        .map(([k, v]) => `<div class="sc-cue"><i>${k}</i><span>${C.esc(v)}</span></div>`).join('');
      beats.forEach((el) => el.classList.toggle('act', +el.dataset.i === i));
    }

    // the read-head follows whatever is in the middle of the viewport
    const io = new IntersectionObserver((es) => {
      es.forEach((e) => { if (e.isIntersecting) App.select(+e.target.dataset.i); });
    }, { root: doc, rootMargin: '-45% 0px -45% 0px' });
    beats.forEach((b) => io.observe(b));

    root.addEventListener('input', (e) => {
      const el = e.target;
      if (!el.dataset || !el.dataset.f) return;
      const b = m.beats[+el.dataset.i], v = el.innerText.replace(/\n/g, '');
      if (el.dataset.f === 'objective') b.objective = v; else b.say.text = v;
      App.change();
    });
    // re-render the '#' markers once the caret leaves, so typing can't inherit them
    root.addEventListener('focusout', (e) => {
      const el = e.target;
      if (!el.dataset || !el.dataset.f) return;
      const b = m.beats[+el.dataset.i];
      el.innerHTML = body(el.dataset.f === 'objective' ? b.objective : b.say.text);
    });
    root.addEventListener('click', (e) => {
      const b = e.target.closest('.sc-beat');
      if (b) App.select(+b.dataset.i);
    });

    App.on('select', () => {
      paint();
      const el = beats[App.selected];
      if (el && !isVisible(el)) el.scrollIntoView({ block: 'center' });
    });
    App.on('change', paint);
    const isVisible = (el) => {
      const r = el.getBoundingClientRect();
      return r.top > 40 && r.bottom < innerHeight - 40;
    };
    new ResizeObserver(paint).observe(cv);
    paint();
  },
};
