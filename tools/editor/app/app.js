/* The editor shell: which mission is open, what is unsaved, and who is driving.
 *
 * Editing is local and instant — nothing leaves the browser until you apply.
 * Apply is explicit and is also save: ctrl/cmd-S writes the YAML, lints it,
 * builds it, copies it into the install, reloads the mod and puts the game back
 * where you were. A lint failure aborts before anything reaches the disk, so the
 * game never runs a mission that is not in the file.
 */
(function () {
  'use strict';

  const $ = (s) => document.querySelector(s);
  const subs = { select: [], change: [], reload: [], live: [] };

  const App = window.App = {
    mission: null, stem: null, path: null, selected: 0, dirty: false,
    on(evt, cb) { (subs[evt] || (subs[evt] = [])).push(cb); },
    emit(evt, a) { (subs[evt] || []).forEach((cb) => cb(a)); },

    select(i, opts) {
      if (!App.mission) return;
      i = Math.max(0, Math.min(App.mission.beats.length - 1, i));
      if (i === App.selected) return;
      App.selected = i;
      App.emit('select');
      // `fromGame` is the game telling us where it already is — seeking back to
      // it would be an echo. Every other selection seeks.
      if (!(opts && opts.fromGame)) seekSoon();
    },
    change() { App.dirty = true; paintChrome(); App.emit('change'); },
    toast,
  };

  // ------------------------------------------------------------------ chrome
  let toastTimer = null;
  function toast(msg, kind) {
    const el = $('#toast');
    el.textContent = msg;
    el.className = 'on ' + (kind || '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (el.className = kind || ''), kind === 'bad' ? 5200 : 2600);
  }

  function showLint(errors, warnings) {
    const box = $('#lintbox');
    const rows = (errors || []).map((e) => `<div>${Core.esc(e)}</div>`)
      .concat((warnings || []).map((w) => `<div class="warn">warn: ${Core.esc(w)}</div>`));
    if (!rows.length) { box.className = ''; box.innerHTML = ''; return; }
    box.innerHTML = `<h6>${(errors || []).length} lint error(s) — nothing was written</h6>` + rows.join('');
    box.className = 'on';
  }

  /* Core.lint returns both severities in one list. Only the errors block a
     save — a warning is the editor saying "this is probably not what you
     meant", and being sure enough to refuse is a different claim. */
  function lintOf(m) {
    const all = m ? Core.lint(m) : [];
    return { errs: all.filter((e) => !e.warn), warns: all.filter((e) => e.warn) };
  }
  const lintText = (e) => `${e.where}: ${e.msg}`;

  function paintChrome() {
    const { errs, warns } = lintOf(App.mission);
    const lint = $('#top .lint');
    lint.textContent = errs.length ? errs.length + ' lint'
      : warns.length ? warns.length + ' warn' : 'lint clean';
    lint.className = 'chip lint ' + (errs.length ? 'bad' : warns.length ? 'warn' : 'ok');
    $('#top .dirty').hidden = !App.dirty;
    $('#save').className = App.dirty ? 'hot' : '';
    $('#undo').disabled = !Core.Model.canUndo();

    const art = window.Assets, ac = $('#top .art');
    ac.textContent = art && art.ok ? `art · ${Object.keys(art.sprites).length} sprites` : 'no art';
    ac.className = 'chip art ' + (art && art.ok ? 'ok' : 'warn');

    const g = $('#top .gamechip');
    g.textContent = !Live.running ? 'game: not running'
      : !Live.inMission ? 'game: ' + ((Live.state && Live.state.room) || 'loading')
        : `game: rung ${Live.state.beat} · ${Live.paused() ? 'paused' : 'playing'}`;
    $('#pause').disabled = !Live.inMission;
    $('#pause').textContent = Live.paused() ? 'resume' : 'pause';
    $('#edit').disabled = !Live.inMission;
    $('#edit').textContent = Live.editRules() ? 'edit rules: on' : 'real rules';
    $('#edit').className = Live.editRules() ? 'hot' : '';
    $('#ghosts').disabled = !Live.inMission;
    $('#ghosts').textContent = 'ghosts: ' + (Live.mode === 'ghosts' ? 'on' : 'off');
    $('#ghosts').className = Live.mode === 'ghosts' ? 'hot' : '';
    $('#paint').textContent = Paint.state.on ? 'painting storm' : 'paint storm';
    $('#paint').className = Paint.state.on ? 'hot' : '';
    $('#sheet').className = MissionPanel.state.on ? 'hot' : '';
    $('#quit').disabled = !Live.running;
    $('#launch').textContent = Live.running ? 'relaunch' : 'launch';
  }

  // ------------------------------------------------------------------ load
  function loadList() {
    return fetch('api/missions').then((r) => r.json()).then((d) => {
      const seluser = $('#missions');
      seluser.innerHTML = (d.missions || []).map((mm) =>
        `<option value="${mm.stem}">${mm.error ? mm.stem + ' — unreadable'
          : `EP${mm.episode} ${Core.esc(mm.title)} · ${mm.beats} beats`}</option>`).join('');
      return d.missions || [];
    });
  }

  function loadMission(stem) {
    return fetch('api/mission/' + encodeURIComponent(stem)).then((r) => r.json()).then((d) => {
      if (!d.ok) throw new Error(d.why || 'could not load');
      App.mission = d.mission;
      App.stem = d.stem;
      App.path = d.path;
      App.selected = 0;
      App.dirty = false;
      Core.Model.reset();
      $('#missions').value = stem;
      document.title = `EP${d.mission.episode} ${d.mission.title} — BSF mission editor`;
      showLint(d.errors, d.warnings);
      App.emit('reload');
      paintChrome();
      const u = new URL(location); u.searchParams.set('m', stem); history.replaceState(null, '', u);
      return d;
    });
  }

  // ------------------------------------------------------------------ apply
  let applying = false;
  function apply() {
    if (applying || !App.mission) return;
    const errs = Core.lint(App.mission);
    if (errs.length) {
      showLint(errs.map((e) => `${e.where}: ${e.msg}`), []);
      return toast(`${errs.length} lint error(s) — nothing written`, 'bad');
    }
    applying = true;
    $('#save').textContent = 'applying…';
    const rung = Core.numberBeats(App.mission)[App.selected].rung;
    fetch('api/apply', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        stem: App.stem, yaml: Core.toYaml(App.mission),
        reload: Live.running, rung, mission: App.mission.mission,
      }),
    }).then((r) => r.json()).then((d) => {
      if (!d.ok) {
        showLint(d.errors || [d.why || 'apply failed'], d.warnings);
        return toast(`${d.stage}: not applied`, 'bad');
      }
      App.dirty = false;
      showLint([], d.warnings);
      const bad = (d.steps || []).filter((s) => !s.ok);
      if (bad.length) toast(`saved and built, but the game said: ${bad[0].result}`, 'bad');
      else toast(d.stage === 'applied'
        ? `applied to ${App.path} and reloaded · ${d.ms} ms`
        : `saved ${App.path} · ${d.ms} ms${d.installed ? ' · installed' : ''}`, 'good');
      App.emit('reload');
    }).catch((e) => toast('apply failed: ' + e.message, 'bad'))
      .finally(() => { applying = false; $('#save').textContent = 'save + apply'; paintChrome(); });
  }

  // ------------------------------------------------------- editor → game
  /* Selecting a beat seeks, and pauses first. Debounced because scrubbing the
     ruler fires a select per pixel and each one would be a command.
     Suppressed while there are unsaved edits: the rungs the game is holding were
     compiled from the file, so seeking to one after an edit would land somewhere
     that no longer means what the timeline says it means. */
  let seekTimer = null;
  function seekSoon() {
    if (!Live.running || !Live.inMission || App.dirty) return;
    // Claim the game *now*, not when the debounce fires. Selecting a beat while
    // the mission is playing is the moment control changes hands, and until the
    // seek lands the poll would keep dragging the playhead back to wherever the
    // game happens to be — the user's click losing a race against a 400 ms timer.
    Live.busy = true;
    clearTimeout(seekTimer);
    seekTimer = setTimeout(() => {
      const rung = Core.numberBeats(App.mission)[App.selected].rung;
      Live.goto(rung, App.mission.mission).then((d) => {
        if (d && !d.ok && d.why) toast(d.why, 'bad');
      });
    }, 260);
  }

  // ------------------------------------------------------- game → editor
  Live.onchange = function (ev) {
    paintChrome();
    if (ev.ranChanged || ev.beatChanged) App.emit('live');
    // While the game is playing it is the one that knows where the mission is,
    // so the playhead follows it. Paused, the editor is driving and must not
    // fight its own seeks.
    if (Live.inMission && !Live.paused() && !Live.busy && App.mission) {
      const i = Live.beatIndex(App.mission);
      if (i >= 0 && i !== App.selected) App.select(i, { fromGame: true });
    }
  };

  // ------------------------------------------------------------------ wire
  $('#missions').addEventListener('change', (e) => {
    const stem = e.target.value;
    if (App.dirty && !confirm('This mission has unsaved edits. Discard them?')) {
      e.target.value = App.stem; return;
    }
    loadMission(stem).catch((err) => toast(err.message, 'bad'));
  });
  $('#save').onclick = apply;
  $('#undo').onclick = () => {
    if (!Core.Model.canUndo()) return toast('nothing to undo');
    Core.Model.undo(App.mission);
    App.selected = Math.min(App.selected, App.mission.beats.length - 1);
    App.emit('reload'); paintChrome();
  };
  $('#launch').onclick = () => {
    const go = () => Live.launch(App.mission ? App.mission.mission : null).then((d) => {
      toast(d.ok ? 'launching the game…' : (d.why || 'could not launch'), d.ok ? 'good' : 'bad');
    });
    if (Live.running) Live.stop().then(() => setTimeout(go, 1200)); else go();
  };
  $('#paint').onclick = () => {
    toast(Paint.toggle() ? 'storm brush — drag on the map, alt erases' : 'storm brush off');
    paintChrome();
  };
  $('#sheet').onclick = () => { MissionPanel.toggle(); paintChrome(); };
  $('#quit').onclick = () => Live.stop().then(() => toast('stopped'));
  $('#pause').onclick = () => Live.setPause(!Live.paused()).then(paintChrome);
  $('#edit').onclick = () => Live.setEdit(!Live.editRules()).then(paintChrome);
  $('#ghosts').onclick = () => {
    Live.mode = Live.mode === 'ghosts' ? 'off' : 'ghosts';
    if (Live.mode === 'ghosts') Live.cmd('dump');
    paintChrome(); App.emit('live');
  };

  addEventListener('keydown', (e) => {
    const t = e.target, tag = t && t.tagName;
    const typing = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (t && t.isContentEditable);
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') { e.preventDefault(); return apply(); }
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); return $('#undo').click(); }
    if (typing) return;
    // The brush owns its keys while it is up, so `1`/`2`/`e` do not have to be
    // free for the rest of the editor to grow into.
    if (Paint.key(e)) { e.preventDefault(); paintChrome(); return; }
    if (MissionPanel.key(e)) { e.preventDefault(); paintChrome(); return; }
    // After the brush, which owns digits while it is up, and before the arrows:
    // zoom changes nothing about the mission, so it needs no chrome repaint.
    if (View.key(e)) { e.preventDefault(); return; }
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { App.select(App.selected + 1); e.preventDefault(); }
    if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { App.select(App.selected - 1); e.preventDefault(); }
    if (e.key === ' ') { e.preventDefault(); if (Live.inMission) $('#pause').click(); }
    if (e.key === 'g') { if (Live.inMission) $('#ghosts').click(); }
  });

  addEventListener('beforeunload', (e) => {
    if (App.dirty) { e.preventDefault(); e.returnValue = ''; }
  });

  // ------------------------------------------------------------------ boot
  document.getElementById('editor-css').textContent = Inspector.css;
  const want = new URLSearchParams(location.search).get('m');

  loadList().then((list) => {
    if (!list.length) throw new Error('no missions in campaign/missions/');
    const stem = list.some((x) => x.stem === want) ? want : list[0].stem;
    return loadMission(stem);
  }).then(() => {
    Inspector.mount(document.getElementById('stage'), {});
    Live.start();
    paintChrome();
  }).catch((e) => toast(e.message, 'bad'));

  /* Art arrives from the server one sprite at a time, and each arrival wants
     the same thing: draw again, now with that image. Coalesced to one repaint a
     frame, because "one full repaint per Image.onload" is thirty of them during
     load — a station's scene alone pulls fourteen sprites — each drawing
     slightly more art than the last and none of them ever seen. */
  let queued = false;
  const artArrived = () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; App.emit('change'); });
  };
  Assets.onload = artArrived;
  // Ship designs are scanned on demand, but the picker and the map both want
  // the list before the first paint, and a scene that finishes loading later
  // has to reach the canvas it was going to be drawn on.
  Ships.onload = artArrived;
  Ships.refresh().then(() => { App.emit('reload'); paintChrome(); });
  Assets.init().then((a) => {
    if (!a.ok) console.warn('art unavailable:', a.why);
    paintChrome();
    App.emit('reload');
  });
})();
