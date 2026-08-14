/* VARIANT D — Source. The YAML is the mission, so the YAML is the editor: type
 * on the left, watch the compiled l_messagecount ladder and the predicted map
 * update on every keystroke. Put the caret inside a beat and that beat lights up
 * in the ladder, on the map and in the tracer log. */
window.VARIANTS = window.VARIANTS || {};
window.VARIANTS.D = {
  name: 'Source',
  blurb: 'yaml left · compiled ladder right',
  css: `
.ide { display:grid; grid-template-rows:34px 1fr; height:100vh; }
.ide-top { display:flex; align-items:center; gap:12px; padding:0 12px; border-bottom:1px solid var(--rule); background:var(--panel); }
.ide-top .path { font-size:11px; color:var(--ink-dim); }
.ide-top .path b { color:var(--log); font-weight:400; }
.ide-chip { font-size:10px; letter-spacing:.1em; text-transform:uppercase; padding:3px 7px; border:1px solid var(--rule); border-radius:2px; color:var(--ink-faint); }
.ide-chip.ok { color:var(--phos); border-color:rgba(78,240,138,.35); }
.ide-chip.bad { color:var(--hostile); border-color:rgba(255,90,77,.45); }
.ide-body { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr) 320px; min-height:0; }
.ide-pane { display:grid; grid-template-rows:24px minmax(0,1fr); min-width:0; min-height:0; border-right:1px solid var(--rule); }
.ide-h { font-size:9px; letter-spacing:.16em; text-transform:uppercase; color:#3f5a55; padding:7px 10px 0;
         background:var(--panel); border-bottom:1px solid var(--rule-soft); }
.ide-h em { font-style:normal; color:var(--ink-faint); float:right; }
.ide-src { position:relative; display:grid; grid-template-columns:44px minmax(0,1fr); min-width:0; min-height:0; background:#070c0d; }
.ide-gut { overflow:hidden; text-align:right; padding:10px 8px 0 0; font:12px/1.55 var(--mono); color:#233130; user-select:none; }
.ide-ta { border:0; outline:none; resize:none; background:transparent; color:var(--ink);
          font:12px/1.55 var(--mono); padding:10px 12px 40vh 0; tab-size:2; white-space:pre; overflow:auto; }
.ide-ta::selection { background:rgba(78,240,138,.25); }
.ide-out { overflow:auto; background:#070c0d; padding:8px 0 40vh; }
.ide-rung { padding:5px 12px; border-left:2px solid transparent; cursor:pointer; }
.ide-rung:hover { background:#0b1214; }
.ide-rung.sel { background:#0e1719; border-left-color:var(--phos); }
.ide-rung .lbl { font-size:9px; letter-spacing:.1em; text-transform:uppercase; color:#3f5a55; }
.ide-rung.sel .lbl { color:var(--phos); }
.ide-rung pre { margin:2px 0 0; font:11.5px/1.5 var(--mono); color:var(--ink-dim); white-space:pre-wrap; word-break:break-word; }
.ide-rung .kw { color:var(--phos); } .ide-rung .fn { color:var(--log); } .ide-rung .num { color:var(--amber); }
.ide-side { display:grid; grid-template-rows:auto auto 1fr; min-height:0; background:var(--panel); }
.ide-side canvas { display:block; width:100%; height:190px; border-bottom:1px solid var(--rule); }
.ide-lint { border-bottom:1px solid var(--rule); padding:8px 10px; font-size:10.5px; line-height:1.7; max-height:26vh; overflow:auto; }
.ide-lint .e { color:var(--hostile); } .ide-lint .w { color:var(--ink-faint); }
.ide-log { overflow:auto; padding:8px 10px; font-size:10.5px; line-height:1.75; color:var(--ink-faint); }
.ide-log .t { color:#2f4340; } .ide-log .b { color:var(--phos); } .ide-log .g { color:var(--amber); }
.ide-log .live { color:var(--hostile); }
`,

  mount(root) {
    const C = Core;
    let m = App.mission;

    root.innerHTML = `
<div class="ide">
  <div class="ide-top">
    <span class="path">campaign/missions/<b>ep9.yaml</b></span>
    <span class="ide-chip" id="d-parse"></span>
    <span class="ide-chip" id="d-lint"></span>
    <span style="flex:1"></span>
    <span class="ide-chip" id="d-beat"></span>
  </div>
  <div class="ide-body">
    <div class="ide-pane">
      <div class="ide-h">source <em>edited live · nothing written to disk</em></div>
      <div class="ide-src">
        <div class="ide-gut" id="d-gut"></div>
        <textarea class="ide-ta" id="d-ta" spellcheck="false"></textarea>
      </div>
    </div>
    <div class="ide-pane">
      <div class="ide-h">compiled — user event 0 (7:10) <em>build.py output</em></div>
      <div class="ide-out" id="d-out"></div>
    </div>
    <div class="ide-side">
      <canvas id="d-cv"></canvas>
      <div class="ide-lint" id="d-lintbox"></div>
      <div class="ide-log" id="d-log"></div>
    </div>
  </div>
</div>`;

    const ta = root.querySelector('#d-ta');
    const gut = root.querySelector('#d-gut');
    const out = root.querySelector('#d-out');
    const cv = root.querySelector('#d-cv');
    ta.value = window.MISSION_YAML;

    let ranges = [];   // beat index -> [firstLine, lastLine] in the textarea
    function computeRanges(text) {
      const lines = text.split('\n');
      const bl = lines.findIndex((l) => /^beats:\s*$/.test(l));
      ranges = [];
      if (bl < 0) return;
      let itemIndent = null;
      for (let i = bl + 1; i < lines.length; i++) {
        const mm = lines[i].match(/^(\s*)- /);
        if (!mm) continue;
        if (itemIndent == null) itemIndent = mm[1].length;
        if (mm[1].length !== itemIndent) continue;
        if (ranges.length) ranges[ranges.length - 1][1] = i - 1;
        ranges.push([i, lines.length - 1]);
      }
    }

    function gutter() {
      const n = ta.value.split('\n').length;
      let s = '';
      for (let i = 1; i <= n; i++) s += i + '\n';
      gut.textContent = s;
      gut.scrollTop = ta.scrollTop;
    }

    const hl = (s) => C.esc(s)
      .replace(/\b(if|else|var|exit|with|repeat)\b/g, '<span class="kw">$1</span>')
      .replace(/\b([a-zA-Z_]\w*)\(/g, '<span class="fn">$1</span>(')
      .replace(/\b(\d+)\b/g, '<span class="num">$1</span>');

    function renderLadder() {
      const numbered = C.numberBeats(m);
      const { startStmts, rungs } = C.emitLadder(m);
      const blocks = [`<div class="ide-rung" data-i="0"><div class="lbl">alarm[2] — opening beat, counter 0</div>
         <pre>${hl(startStmts.join(';\n') + ';')}</pre></div>`];
      rungs.forEach((r, k) => {
        const bi = numbered[k + 1].i;
        blocks.push(`<div class="ide-rung" data-i="${bi}">
          <div class="lbl">if (l_messagecount = ${r.n})</div>
          <pre>${hl(r.body.join(';\n') + ';')}</pre></div>`);
      });
      out.innerHTML = blocks.join('');
    }

    function renderSide() {
      C.drawMap(cv, { mission: m, reveal: App.selected, focus: m.beats[App.selected], pad: 10, labels: false });
      const errs = C.lint(m);
      root.querySelector('#d-lintbox').innerHTML = errs.length
        ? errs.map((e) => `<div class="e">✗ ${C.esc(e.where)}: ${C.esc(e.msg)}</div>`).join('')
        : `<div class="w">lint clean — ${m.beats.length} beats, ${C.emitLadder(m).texts.length} dialogue globals,
           ${m.gates.length} gates, ${m.zones.length} zones. Resource names would also be checked
           against the extracted object/script inventory.</div>`;
      const lc = root.querySelector('#d-lint');
      lc.textContent = errs.length ? errs.length + ' lint' : 'lint clean';
      lc.className = 'ide-chip ' + (errs.length ? 'bad' : 'ok');
      root.querySelector('#d-beat').textContent = `beat ${App.selected} · rung ${C.numberBeats(m)[App.selected].n}`;
      // mock of the beatlog tracer build.py would inject into the generated GML
      const log = [];
      let step = 45;
      for (let i = 0; i <= App.selected; i++) {
        const b = m.beats[i], n = C.numberBeats(m)[i].n;
        step += 60 + (b.say ? 180 : 20) + (b.wait === 'gate' ? 400 : 0);
        log.push(`<div><span class="t">${String(step).padStart(5)}</span> <span class="b">beat ${n}</span> ${C.esc(C.actionsOf(b, m).map((a) => a.label).join(' ') || 'idle')}</div>`);
        if (b.wait === 'gate') log.push(`<div><span class="t">${String(step + 210).padStart(5)}</span> <span class="g">gate</span> MoveToArea reached, counter +1</div>`);
      }
      log.push('<div class="live">● waiting for the running game…</div>');
      root.querySelector('#d-log').innerHTML =
        '<div class="t" style="margin-bottom:4px">mods/beatlog.txt — tracer (mock)</div>' + log.join('');
    }

    let t = null;
    function reparse() {
      const chip = root.querySelector('#d-parse');
      try {
        const doc = C.parseYaml(ta.value);
        if (!doc || !doc.beats || !doc.beats.length) throw new Error('no beats');
        App.mission = m = doc;
        App.selected = Math.min(App.selected, m.beats.length - 1);
        chip.textContent = `parsed ✓ ${m.beats.length} beats`;
        chip.className = 'ide-chip ok';
        computeRanges(ta.value);
        renderLadder(); renderSide();
      } catch (e) {
        chip.textContent = 'parse: ' + e.message;
        chip.className = 'ide-chip bad';
      }
    }

    function caretBeat() {
      const line = ta.value.slice(0, ta.selectionStart).split('\n').length - 1;
      for (let i = ranges.length - 1; i >= 0; i--) if (line >= ranges[i][0]) return i;
      return App.selected;
    }

    ta.addEventListener('input', () => { gutter(); clearTimeout(t); t = setTimeout(reparse, 180); });
    ta.addEventListener('scroll', () => { gut.scrollTop = ta.scrollTop; });
    ['click', 'keyup'].forEach((ev) => ta.addEventListener(ev, () => {
      const i = caretBeat();
      if (i !== App.selected) App.select(i);
    }));
    out.addEventListener('click', (e) => {
      const r = e.target.closest('.ide-rung');
      if (!r) return;
      App.select(+r.dataset.i);
      const rg = ranges[+r.dataset.i];
      if (rg) {
        const pos = ta.value.split('\n').slice(0, rg[0]).join('\n').length + 1;
        ta.focus(); ta.setSelectionRange(pos, pos);
        ta.scrollTop = Math.max(0, (rg[0] - 6) * 12 * 1.55);
        gut.scrollTop = ta.scrollTop;
      }
    });

    App.on('select', () => {
      out.querySelectorAll('.ide-rung').forEach((r) => r.classList.toggle('sel', +r.dataset.i === App.selected));
      const sel = out.querySelector('.ide-rung.sel');
      if (sel) sel.scrollIntoView({ block: 'nearest' });
      renderSide();
    });
    new ResizeObserver(() => renderSide()).observe(cv);

    gutter(); computeRanges(ta.value); reparse();
    out.querySelectorAll('.ide-rung').forEach((r) => r.classList.toggle('sel', +r.dataset.i === App.selected));
  },
};
