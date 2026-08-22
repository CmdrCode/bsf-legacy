/* The inspector: the editing model that won round two.
 *
 * The NLE answer. The timeline is the *arrangement* and a docked rail is the
 * *detail*: blocks on the track stay compact and read-only, and selecting one
 * turns every verb it carries into a card of fields. Structure is edited on the
 * track — drag a block to reorder, `+` in a gap to insert — and content is edited
 * in the rail. Nothing is edited in two places, which is what beat direct
 * manipulation (drag verbs from a palette) and the modal command line.
 */
window.Inspector = (function () {
  'use strict';

  const css = TL.css + Paint.css + Handles.css + View.css + MissionPanel.css + `
/* The rail takes its space out of the map rather than covering it. */
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
.card.spawn { border-left-color:var(--alien); } .card.gate, .card.gate_at { border-left-color:var(--phos); }
.card.camera, .card.ping { border-left-color:#7aa0c8; } .card.exec { border-left-color:var(--amber); }
.card.interference { border-left-color:var(--hostile); }
/* The three that change what the *player* may do or see, rather than what is
   in the room — amber, the colour this editor already uses for a lever. */
.card.controls, .card.surge, .card.bounds { border-left-color:var(--amber); }
.card > h5 { margin:0; padding:5px 8px; font:9.5px/1 var(--mono); letter-spacing:.14em; text-transform:uppercase;
             color:var(--ink-faint); display:flex; justify-content:space-between; border-bottom:1px solid var(--rule-soft); }
.card > h5 .x { cursor:pointer; color:#3f5a55; }
.card > h5 .x:hover { color:var(--hostile); }
.card .rows { padding:6px 8px; display:grid; grid-template-columns:auto minmax(0,1fr); gap:4px 8px; align-items:center; }
.card label { font-size:9px; letter-spacing:.1em; text-transform:uppercase; color:#3f5a55; }
/* Per-entry strip, for the one verb that is a list. It is a header, not a
   field: full width, its own rule above it, and a remove that says "remove"
   rather than being a six-pixel glyph tucked into the label column. */
.card .rows .full { grid-column:1 / -1; }
.card .sub { display:flex; justify-content:space-between; align-items:center; gap:8px;
  margin:2px 0 1px; padding:5px 0 4px; border-top:1px solid var(--rule-soft);
  font:9.5px/1.3 var(--mono); letter-spacing:.12em; text-transform:uppercase; color:var(--ink-faint); }
.card .rows > .full:first-child .sub { margin-top:0; padding-top:1px; border-top:0; }
.card .sub .x { cursor:pointer; color:#5d6d68; padding:2px 5px; border:1px solid transparent;
  border-radius:2px; white-space:nowrap; }
.card .sub .x:hover { color:var(--hostile); border-color:rgba(255,90,77,.45); }
.card input, .card select, .card textarea { font:11px/1.45 var(--mono); background:#070d0e; color:var(--ink);
  border:1px solid var(--rule); border-radius:2px; padding:3px 5px; width:100%; }
.card input:focus, .card textarea:focus, .card select:focus { outline:none; border-color:var(--phos); }
.card .xy { display:flex; gap:5px; }
.card .chks { display:flex; gap:14px; flex-wrap:wrap; padding:1px 0 2px; }
.card .chk { display:flex; align-items:center; gap:5px; cursor:pointer; font-size:10.5px;
  color:var(--ink); letter-spacing:.06em; }
.card .chk input { width:auto; margin:0; accent-color:var(--phos); cursor:pointer; }
.card .note { font-size:10px; color:var(--ink-faint); }
.ins-add { display:flex; flex-wrap:wrap; gap:4px; margin-top:8px; }
.ins-add button, .ins-f button, .card button { all:unset; cursor:pointer; font:9.5px/1 var(--mono); letter-spacing:.08em;
  text-transform:uppercase; padding:5px 7px; border:1px solid var(--rule); border-radius:2px; color:var(--ink-dim); }
.ins-add button:hover, .ins-f button:hover, .card button:hover { border-color:var(--phos); color:var(--phos); }
.card button { margin-top:4px; font-size:9px; }
.card input::placeholder { color:#33474450; }
.ins-f { display:flex; gap:4px; padding:8px 12px; border-top:1px solid var(--rule); }
.ins-f button.del:hover { border-color:var(--hostile); color:var(--hostile); }
/* the track */
.blk { position:absolute; top:5px; bottom:5px; border:1px solid var(--rule); border-left:2px solid #2f4340;
       background:#0b1214; border-radius:2px; padding:5px 7px; cursor:grab; overflow:hidden;
       user-select:none; -webkit-user-select:none; }
.blk:hover { background:#101a1b; }
.blk.sel { border-color:var(--phos); border-left-color:var(--phos); background:#0f1a18; }
.blk.live { border-left-color:var(--ghost); }
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
/* Real art: the portrait a say will actually show, and the sprite a spawn will
   actually be — pulled from the exe, so a wrong resource name is visibly wrong
   while you type it rather than at build time. */
.spr, .sprgrid, .menu { user-select:none; -webkit-user-select:none; }
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
/* The object picker has 600-odd entries, so it filters. The popup becomes a
   column: the filter stays put and everything under it scrolls.

   ONE scroll region, not one per section. Every .grid used to scroll itself,
   which was invisible while there were two of them and wrong as soon as there
   were three — flex shared the height out, so 25 ships got a single visible row
   with a scrollbar of its own and the eye had no way to run designs → ships →
   props. The sections scroll together; only the filter is pinned. */
.sprgrid.objs { display:flex; flex-direction:column; gap:6px; width:328px; overflow:hidden; }
.sprgrid.objs .filt { font:10.5px/1.4 var(--mono); background:#070d0e; color:var(--ink);
  border:1px solid var(--rule); border-radius:2px; padding:4px 6px; flex:none; }
.sprgrid.objs .filt:focus { outline:none; border-color:var(--phos); }
.sprgrid.objs .scroll { overflow:auto; display:flex; flex-direction:column; gap:6px; }
.sprgrid.objs .grid { display:grid; grid-template-columns:repeat(4,74px); gap:6px; }
.sprgrid.objs .head { font:9px/1 var(--mono); letter-spacing:.14em; text-transform:uppercase;
  color:#3f5a55; padding:4px 2px 2px; border-top:1px solid var(--rule-soft); flex:none; }
.sprgrid.objs .head:first-of-type { border-top:0; }
.sprgrid canvas.shipthumb { width:56px; height:56px; display:block; margin:0 auto; image-rendering:pixelated; }
.spr canvas.shipthumb { width:46px; height:46px; }
.stale { color:var(--amber); font-weight:400; }
.card .note.stale { color:var(--amber); }
.menu { position:fixed; z-index:70; background:#0b1214; border:1px solid var(--rule); border-radius:2px; padding:3px; }
.menu button { all:unset; display:block; cursor:pointer; font:10px/1 var(--mono); padding:6px 10px; color:var(--ink-dim); border-radius:2px; }
.menu button:hover { background:#152021; color:var(--phos); }
`;

  function mount(root, opts) {
    const C = Core, M = C.Model;
    const m = () => App.mission;
    const refs = TL.mount(root, {
      bw: 152, lane: 84,
      transportExtra: opts.transportExtra || '',
      viewExtra: `<aside class="ins"><div class="ins-h"></div><div class="ins-b"></div><div class="ins-f">
        <button data-op="before">+ before</button><button data-op="after">+ after</button>
        <button data-op="dup">duplicate</button>
        <button data-op="del" class="del">delete</button></div></aside>`,
    });

    // ---------------------------------------------------------------- track
    function renderTrack() {
      const mm = m(), N = mm.beats.length, BW = refs.bw;
      const blocks = mm.beats.map((b, i) =>
        `<div class="blk" data-i="${i}" style="left:${TL.LEFT + i * BW}px;width:${BW - 6}px">${TL.blockInner(b, mm)}</div>`);
      const gaps = [];
      for (let i = 1; i <= N; i++) gaps.push(`<div class="gap" data-at="${i}" style="left:${TL.LEFT + i * BW - 10}px"></div>`);
      refs.beats.innerHTML = blocks.join('') + gaps.join('');
      markTrack();
    }
    function markTrack() {
      const live = Live.beatIndex(m());
      refs.beats.querySelectorAll('.blk').forEach((el) => {
        const i = +el.dataset.i;
        el.classList.toggle('sel', i === App.selected);
        el.classList.toggle('live', i === live);
      });
    }

    // ------------------------------------------------------------ inspector
    /* A sprite field, shown as the sprite: the portrait GUI_Messager will draw,
       at its real size and origin — or a red "not in tree", which is exactly what
       build.py's lint would reject, made visible while you type it. */
    function sprField(path, name, filter) {
      const A = window.Assets, s = A && A.ok ? A.sprites[name] : null;
      const thumb = !A || !A.ok
        ? '<div class="thumb dim">no art</div>'
        : s ? `<div class="thumb"><img src="api/sprite/${encodeURIComponent(name)}?f=0" alt=""></div>`
          : '<div class="thumb miss">not in tree</div>';
      return `<div class="spr" data-pick="${path}" data-filter="${filter}">${thumb}
        <div><div class="nm">${C.esc(name)}</div>
        <div class="dim">${s ? `${s.w}×${s.h} · origin ${s.ox},${s.oy}${s.n > 1 ? ' · ' + s.n + ' frames' : ''}` : 'click to pick'}</div></div></div>`;
    }

    /* What a spawned object will look like: its own sprite_index, tinted the way
       its Create event tints it. Masks drawn untinted are black boxes.

       Clickable, like a portrait: the object *is* the prop, so "which station"
       and "which planet" are the same question as "which object", and typing a
       name into a text field is not a way to answer a question with 600 answers
       in it. */
    function objPreview(obj, k, sp) {
      const A = window.Assets;
      // A design has no single sprite — it is a hull — so it previews as itself,
      // drawn into a canvas from the same scene the map uses.
      if (sp && sp.ship) {
        const info = window.Ships ? Ships.info(sp.ship) : null;
        return `<div class="spr" data-opick="${k}">
          <canvas class="thumb shipthumb" width="46" height="46" data-ship="${C.esc(sp.ship)}"></canvas>
          <div><div class="nm">${C.esc((info && (info.title || info.name)) || C.spawnLabel(sp))}</div>
          <div class="dim">${C.esc(sp.ship)} · click to change</div></div></div>`;
      }
      if (!A || !A.ok) return '<span class="note">no art</span>';
      // A ship object is previewed as its hull for the same reason a design is:
      // it has no sprite worth showing. Every stock hull's `sprite_index` is
      // spr_Core, so the sprite preview named the Hestia "spr_Core" and drew a
      // four-pixel core section — the same picture, and the same caption, for
      // every ship in the game.
      if (A.isShip(obj)) {
        return `<div class="spr" data-opick="${k}">
          <canvas class="thumb shipthumb" width="46" height="46" data-obj="${C.esc(obj)}"></canvas>
          <div><div class="nm">${C.esc(obj)}</div>
          <div class="dim">a ship the game compiles in · click to change</div></div></div>`;
      }
      const nm = A.spriteOf(obj);
      const s = nm && A.sprites[nm];
      return `<div class="spr" data-opick="${k}">${s
        ? `<div class="thumb"><img src="api/sprite/${encodeURIComponent(nm)}?f=0" alt=""></div>`
        : '<div class="thumb miss">unknown object</div>'}
        <div><div class="nm">${C.esc(nm || obj)}</div>
        <div class="dim">${s ? `${s.w}×${s.h}${s.mask ? ' · palette mask' : ''}`
          : 'not in objects_rt'} · click to change</div></div></div>`;
    }

    /* Hull thumbnails are canvases, not <img>: a hull has no single sprite, so
       each one is drawn section by section with the map's own blitter. Both
       kinds arrive late, so both repaint from here.

       Two kinds and two owners of the draw: `data-ship` is a design file, drawn
       from scene.py's list by Ships; `data-obj` is one of the game's own ship
       objects, drawn from its dump by Assets. Same class, so one sweep repaints
       both, and a caller that knows about neither can ask for a repaint. */
    function paintShipThumbs(root2) {
      (root2 || document).querySelectorAll('canvas.shipthumb').forEach((c) => {
        if (c.dataset.obj) { if (window.Assets) Assets.shipThumb(c, c.dataset.obj, 3); }
        else if (window.Ships) Ships.thumb(c, c.dataset.ship, 3);
      });
    }

    /* The three pickers below are the same object: a panel placed at the
       pointer, clamped so it cannot open off-screen, dismissed by the first
       click outside it. Written out three times, the dismissal rule was three
       copies of the same eight tokens — fix one and the other two keep the bug.

       The timeout is load-bearing and not a workaround: the click that opened
       the popup is still propagating, so a listener added synchronously would
       see it and close the popup in the same gesture that asked for it. */
    function popup(cls, x, y, w, h, html) {
      const el = document.createElement('div');
      el.className = cls;
      el.style.left = Math.min(x, innerWidth - w) + 'px';
      el.style.top = Math.min(y, innerHeight - h) + 'px';
      el.innerHTML = html;
      document.body.appendChild(el);
      setTimeout(() => addEventListener('pointerdown', function off(ev) {
        if (!el.contains(ev.target)) { el.remove(); removeEventListener('pointerdown', off); }
      }), 0);
      return el;
    }

    /* Every object the art layer knows, drawn as itself. The same grid as the
       sprite picker and deliberately so — but keyed on the object, because a
       spawn names an object and the sprite is a consequence of it. */
    function objectPicker(x, y, current, cb) {
      const A = window.Assets;
      if (!A || !A.ok) return App.toast('no game art — the server could not find BattleshipsForever.exe', 'bad');
      const names = Object.keys(A.objects).sort();
      // Three sections, because they are three different things. A DESIGN is a
      // file the game loads with importShip; the other two are objects compiled
      // into the game, but a SHIP and a PROP are not picked the same way. A
      // prop is its sprite, so the sprite is the answer to "which one". A ship
      // is a hull that ignores its sprite — all of them are spr_Core — so a
      // grid of sprites showed a hundred identical four-pixel squares and the
      // Hestia could not be told from the Athena. Ships draw as hulls.
      const designList = (window.Ships && Ships.state.list) || [];
      const designs = designList.length ? `<div class="head">designs — loaded from a file</div>`
        + `<div class="grid">${designList.map((s) => `<figure data-ship="${C.esc(s.file)}">
        <canvas class="shipthumb" width="56" height="56" data-ship="${C.esc(s.file)}"></canvas>
        <figcaption>${C.esc(s.name)}${s.stale ? ' <b class="stale">stale</b>' : ''}</figcaption></figure>`).join('')}</div>`
        : '';
      const shipObjs = names.filter((n) => A.isShip(n));
      const propObjs = names.filter((n) => !A.isShip(n));
      // Both sections carry `data-n`: a stock hull is still recorded as
      // `object:`, so how it is drawn here changes nothing about what picking
      // it means — and the filter and the click handler need no special case.
      const ships = shipObjs.length ? `<div class="head">ships — compiled into the game</div>`
        + `<div class="grid">${shipObjs.map((n) => `<figure class="${n === current ? 'on' : ''}" data-n="${n}">
        <canvas class="shipthumb" width="56" height="56" data-obj="${C.esc(n)}"></canvas>
        <figcaption>${n}</figcaption></figure>`).join('')}</div>`
        : '';
      const el = popup('sprgrid objs', x, y, 340, 380,
        `<input class="filt" placeholder="filter — hestia, station, planet…">`
        + `<div class="scroll">`
        + designs
        + ships
        + `<div class="head">props — scenery, markers, everything else</div>`
        + `<div class="grid">${propObjs.map((n) => `<figure class="${n === current ? 'on' : ''}" data-n="${n}">
        <img src="api/sprite/${encodeURIComponent(A.objects[n])}?f=0" alt="" loading="lazy">
        <figcaption>${n}</figcaption></figure>`).join('')}</div>`
        + `</div>`);
      el.style.maxHeight = '60vh';
      // The figures and their search keys are built once and never change, so
      // the filter walks an array it already holds rather than re-querying
      // 600-odd nodes out of the DOM on every keystroke.
      const figs = [...el.querySelectorAll('figure')]
        .map((f) => [f, f.dataset.n || f.dataset.ship || '']);
      // A section whose figures are all filtered out hides its heading too. With
      // one grid there was nothing to hide; with three, a filter that matches
      // only props leaves "ships —" ruled off above an empty space, which reads
      // as a section that failed to load rather than one with no matches.
      const sections = [...el.querySelectorAll('.head')].map((h) => [h, h.nextElementSibling]);
      el.querySelector('.filt').addEventListener('input', (ev) => {
        const re = new RegExp(ev.target.value.replace(/[^\w\s-]/g, ''), 'i');
        figs.forEach(([f, key]) => { f.hidden = !re.test(key); });
        sections.forEach(([h, g]) => {
          const any = !!g && [...g.children].some((f) => !f.hidden);
          h.hidden = !any;
          if (g) g.hidden = !any;
        });
      });
      el.addEventListener('click', (ev) => {
        const f = ev.target.closest('figure');
        if (!f) return;
        el.remove();
        cb(f.dataset.ship ? { ship: f.dataset.ship } : f.dataset.n);
      });
      paintShipThumbs(el);
      setTimeout(() => { el.querySelector('.filt').focus(); }, 0);
    }

    function sel(path, cur, opts_, label) {
      return `<select data-p="${path}">` + opts_.map((o) =>
        `<option value="${o}"${String(o) === String(cur) ? ' selected' : ''}>${C.esc(label ? label(o) : o)}</option>`).join('') + '</select>';
    }

    const F = {
      /* Why this beat is the way it is. It compiles to nothing and the game
         never sees it — the point is that it is *data*, so the save writes it
         back out. A `#` comment in the mission file does not survive one: the
         editor parses to a model and re-serialises from the model, so a comment
         lives until the next apply and then vanishes without trace.

         Anyone working on a mission should put their reasoning here rather than
         in a comment — measurements, why a number is that number, what was
         tried and rejected. */
      note: (b) => [
        [null, `<textarea data-note rows="6" placeholder="Why this beat is the way it is — measurements, what was tried, what a number was derived from. Saved with the mission; the game never sees it.">${C.esc(C.noteText(b.note))}</textarea>`],
        ['', '<span class="note">kept in the file as <code>note:</code>. Unlike a '
          + '# comment, this survives a save.</span>'],
      ],
      say: (b) => [
        ['who', `<input data-p="say.who" value="${C.esc(b.say.who)}">`],
        ['portrait', sprField('say.sprite', b.say.sprite || 'spr_MesHint', '^spr_Mes')],
        ['colour', sel('say.color', b.say.color || 'green', ['green', 'red', 'magenta', 'white'])],
        ['text', `<textarea data-p="say.text" rows="5">${C.esc(b.say.text)}</textarea>`],
      ],
      objective: (b) => [['text', `<textarea data-p="objective" rows="3">${C.esc(b.objective)}</textarea>`]],
      camera: (b) => [
        ['x / y', `<div class="xy"><input data-p="camera.x" data-num value="${b.camera.x}">
          <input data-p="camera.y" data-num value="${b.camera.y}"></div>`],
        ['speed', `<input data-p="camera.speed" data-num value="${b.camera.speed == null ? 60 : b.camera.speed}">`]],
      spawn: (b) => b.spawn.flatMap((sp, k) => {
        const A = window.Assets;
        const design = !!sp.ship;
        const info = design && window.Ships ? Ships.info(sp.ship) : null;
        const what = (design && info && info.name) || C.spawnLabel(sp);
        // Ship or prop, said out loud. They spawn through the same list but
        // they are not the same kind of thing, and the fields below differ by
        // which one it is — a hull takes team, facing and damage, a prop takes
        // a sprite and a tint.
        const kind = design || (A && A.ok && A.isShip(sp.object)) ? 'ship' : 'prop';
        const rows = [
          [null, `<div class="sub"><span>${kind} ${k + 1} of ${b.spawn.length} · ${C.esc(what)}</span>
            <span class="x" data-rmspawn="${k}" title="remove this ${kind} from the beat">remove ✕</span></div>`],
          [design ? 'ship' : 'object', `<div class="xy">
            <input data-p="spawn.${k}.${design ? 'ship' : 'object'}" value="${C.esc(design ? sp.ship : sp.object)}">
            <input data-p="spawn.${k}.x" data-num value="${sp.x}" style="max-width:62px">
            <input data-p="spawn.${k}.y" data-num value="${sp.y}" style="max-width:62px"></div>`],
          ['', objPreview(sp.object, k, sp)],
        ];
        // A design is a file the game loads, so it carries the one thing the
        // file cannot say: which side it fights for. An object *is* its side.
        if (design) rows.push(
          ['team', sel(`spawn.${k}.team`, sp.team || '', ['', 'player', 'ally', 'enemy'],
            (t) => t || '— required —')]);
        // hold, facing and damage describe a hull, and describe it the same way
        // whether it arrived as a design or as one of the game's own ship
        // objects — these were design-only when `hold:` on an object silently
        // did nothing. Scenery is excluded: a planet has no AI to still and no
        // `name:` is what makes a spawn addressable by anything else in the
        // mission — the ping that announces it, the tick that holds its damage,
        // any GML in an `exec:`. It had no field at all, so a spawn could only
        // be named by hand-editing the YAML, which put `damage:` (which the
        // build *requires* a name for) and the ping link both out of reach of
        // the editor. Optional, so blank removes the key.
        rows.push(['name', `<input data-p="spawn.${k}.name" placeholder="unnamed"
          value="${C.esc(sp.name == null ? '' : sp.name)}"
          title="how the rest of the mission refers to this spawn (global.<mission>_<name>)">`]);
        if (design || (A && A.ok && A.isShip(sp.object))) {
          rows.push(
            ['hold', sel(`spawn.${k}.hold`, sp.hold ? 'yes' : 'no', ['no', 'yes'])],
            ['facing', `<input data-p="spawn.${k}.facing" data-num placeholder="0°"
              value="${sp.facing == null ? '' : sp.facing}" style="max-width:62px"
              title="direction and image_angle; a held hull never turns to face anything">`],
            ['damage', `<input data-p="spawn.${k}.damage" data-num placeholder="1"
              value="${sp.damage == null ? '' : sp.damage}" style="max-width:62px"
              title="section HP multiplier at spawn, held there for the whole mission">`]);
          if (sp.damage != null && Number(sp.damage) < 0.5) rows.push(
            ['', '<span class="note">under half HP, so it smokes — and a mission '
              + 'tick holds it there against the engine repairing it back up</span>']);
          if (sp.hold) rows.push(
            ['', '<span class="note">held: stays put, and the player cannot '
              + 'select it</span>']);
        }
        if (design) {
          if (info && info.stale) rows.push(
            ['', '<span class="note stale">the .sb4 beside this file is newer — '
              + 'the game loads this .shp until it is re-exported from ShipMaker</span>']);
          if (info) rows.push(['', `<span class="note">${info.generation} · ${info.sections} sections · `
            + `${info.mounts} mounts · ${info.root === 'stock' ? 'ships with the game' : 'installs with the campaign'}</span>`]);
        }
        // The look block is only offered for objects the game draws as a sprite.
        // A designed ship draws its sections and ignores `sprite_index`, so a
        // sprite field on one would be a control that does nothing.
        if (!design && A && A.ok && !A.isShip(sp.object)) rows.push(
          ['sprite', sp.sprite
            ? `${sprField(`spawn.${k}.sprite`, sp.sprite, '^spr_')}
               <button data-clear="spawn.${k}.sprite">use the object's own</button>`
            : `<button data-look="${k}" data-add-look="sprite">+ pick a sprite</button>`],
          ['size', `<div class="xy">
            <input data-p="spawn.${k}.scale" data-num placeholder="1" value="${sp.scale == null ? '' : sp.scale}" style="max-width:56px" title="image_xscale / image_yscale">
            <input data-p="spawn.${k}.angle" data-num placeholder="0°" value="${sp.angle == null ? '' : sp.angle}" style="max-width:56px" title="image_angle, counter-clockwise">
            <input data-p="spawn.${k}.frame" data-num placeholder="frame" value="${sp.frame == null ? '' : sp.frame}" style="max-width:56px" title="image_index"></div>`],
          ['tint', `<input data-p="spawn.${k}.tint" placeholder="#rrggbb or a colour word" value="${C.esc(sp.tint == null ? '' : sp.tint)}">`],
          ['', '<span class="note">assigned after the object is created, so these replace what it set for itself. Blank = leave it alone.</span>']);
        // One "+ another" at the end of the list, not one per entry.
        if (k === b.spawn.length - 1) rows.push([null, '<button data-addspawn="1">+ another ship or prop</button>']);
        return rows;
      }),
      gate: (b) => {
        const g = (m().gates || [])[b.gate];
        const rows = [['beacon', sel('gate', b.gate, (m().gates || []).map((_g, k) => k),
          (k) => `${+k + 1} — (${m().gates[k].x}, ${m().gates[k].y})`)]];
        // `gates:` is a mission list, not a per-beat value — say so, because the
        // field sits inside a beat's card and moving it moves every beat's.
        if (g) rows.push(
          ['x / y', `<div class="xy"><input data-gp="${b.gate}.x" data-num value="${g.x}">
            <input data-gp="${b.gate}.y" data-num value="${g.y}"></div>`],
          ['', '<span class="note">the beacon itself — drag it on the map, or type here. Shared: every beat that waits on beacon '
            + (b.gate + 1) + ' uses this position.</span>']);
        rows.push(['wait', sel('wait', b.wait || 'none', ['gate', 'none'])]);
        return rows;
      },
      gate_at: (b) => [['x / y', `<div class="xy"><input data-p="gate_at.x" data-num value="${b.gate_at.x}">
        <input data-p="gate_at.y" data-num value="${b.gate_at.y}"></div>`]],
      /* The ping is the flash that says "look here", so the question it has to
         answer is *what* it is announcing, not where that thing currently is.
         Attach it to a spawn and the position stops being a second copy that
         can fall out of step — which is exactly how EP9's reveal ended up
         pointing 926 units from the ship it was revealing.

         The fixed pair stays, because a ping at a place rather than a thing is
         a real thing to want. */
      ping: (b) => {
        const mm = m();
        const fixed = Array.isArray(b.ping);
        const at = C.pingAt(mm, b);
        // Every spawn in the mission, named or not, plus the player start. An
        // unnamed spawn is offered by address and is given a name when it is
        // picked: a link is stored by name, and a picker that hid the spawn you
        // just placed would be missing exactly when it is wanted.
        const opts = [['player', `player · ${C.spawnLabel({ object: mm.player.object })}`]];
        mm.beats.forEach((bb, bi) => (bb.spawn || []).forEach((sp, si) =>
          opts.push([sp.name || `#${bi}:${si}`,
            `${C.spawnLabel(sp)} · beat ${bi}${sp.name ? ' · ' + sp.name : ''}`])));
        const rows = [['follows',
          '<select data-pinglink>'
          + `<option value=""${fixed ? ' selected' : ''}>a fixed point</option>`
          + opts.map(([v, t]) =>
            `<option value="${C.esc(v)}"${!fixed && String(b.ping) === v ? ' selected' : ''}>`
            + `${C.esc(t)}</option>`).join('')
          + '</select>']];
        if (fixed) {
          rows.push(['x / y', `<div class="xy"><input data-p="ping.0" data-num value="${b.ping[0]}">
            <input data-p="ping.1" data-num value="${b.ping[1]}"></div>`]);
          rows.push(['', '<span class="note">drag the ◎ on the map to move it. A fixed '
            + 'point does not follow a spawn you later move.</span>']);
        } else if (at) {
          rows.push(['at', `<span class="note">(${at.x}, ${at.y}) — from ${C.esc(String(b.ping))}. `
            + 'Move that spawn and the ping moves with it.</span>']);
        } else {
          rows.push(['at', '<span class="note stale">nothing named '
            + C.esc(String(b.ping)) + ' — the build will drop this ping</span>']);
        }
        return rows;
      },
      music: (b) => [['track', sel('music', b.music, ['stop', 'theme', 'battle'])]],
      eerie: (b) => [['state', sel('eerie', C.onoff(b.eerie), ['on', 'off'])]],
      meteors: (b) => [['spawner', sel('meteors', C.onoff(b.meteors), ['on', 'off'])]],
      /* A checkbox per target rather than one on/off, because the two halves of
         this effect say different things and a mission wants them apart: the
         weather does not stop when you dock, but the instruments clear. Both
         ticked writes `interference: on` and neither writes `off`, so a mission
         that never cared about the distinction keeps the file it always had. */
      interference: (b) => {
        const st = C.Interf.state(b.interference);
        const box = (k, label) => `<label class="chk"><input type="checkbox" data-interf="${k}"`
          + `${st[k] ? ' checked' : ''}> ${label}</label>`;
        return [
          [null, `<div class="chks">${box('ships', 'ships')}${box('clouds', 'clouds')}</div>`],
          ['', '<span class="note"><b>clouds</b> — every ter_Nebula, and the storm\'s own gas with it, redrawn additively with a random alpha kick. This is the weather.</span>'],
          ['', '<span class="note"><b>ships</b> — every hull section leaves a jittered half-alpha echo at its previous position. Stock ctr_Mission3, generalised; it is the only effect in the game that makes the <i>player</i> look wrong, which is why it reads as interference and not as weather.</span>'],
        ];
      },
      /* The three flags whose machinery lives in a mission-level block. Each
         card edits the flag and *reports* the block, rather than editing both:
         the block is one setting for the whole mission and belongs in the sheet
         (m), while the flag is a moment in the story and belongs here. Saying
         where the other half is, is the whole job of the note lines. */
      controls: (b) => [
        ['helm', sel('controls', C.onoff(b.controls), ['on', 'off'])],
        ['', '<span class="note"><b>off</b> takes the ship away: it stops being selectable, which is what stops orders, and any live selection is dropped. The camera is pinned where it stands and yields to a scripted pan, so <b>camera:</b> in a later beat still moves the view while the player cannot. <b>on</b> gives it back.</span>'],
        ['', '<span class="note">beat 0 decides the state the room opens in — the compiler reads it at Create, so a mission that locks the helm is locked before the first frame rather than 45 frames in.</span>']],
      surge: (b) => {
        const mm = m(), s = C.Surge.at(mm), has = C.Surge.any(mm);
        return [
          ['wall', sel('surge', C.onoff(b.surge), ['on', 'off'])],
          ['', `<span class="note">the advancing wall of storm. <b>on</b> lights it ${s.back} units behind the ship — behind wherever the ship <i>is</i>, not at a fixed x, so moving this beat moves the wall with it — and it closes at ${s.speed}/step until it parks at x ${s.stop}.</span>`],
          ['', C.Storm.any(mm)
            ? `<span class="note">${has ? 'settings' : 'no <b>surge:</b> block — running on the compiler’s defaults'}: edit them in the mission sheet (<b>m</b>).</span>`
            : '<span class="note stale">no storm: block — the wall is made of storm and will never advance</span>'],
        ];
      },
      bounds: (b) => {
        const x2 = C.Surge.limit(m());
        return [
          ['limit', sel('bounds', C.onoff(b.bounds), ['on', 'off'])],
          ['', x2 == null
            ? '<span class="note stale">no <b>bounds: x2</b> in the mission sheet (<b>m</b>) — this flag has no edge to clamp to and does nothing</span>'
            : `<span class="note">how far right the camera may look, clamped at x ${x2} exactly as the room's own edge clamps it. The ship may still fly past it; only the view stops. A mission carrying <b>bounds:</b> starts clamped, so the beat that names it is normally the one that turns it <b>off</b> — the reveal.</span>`],
        ];
      },
      exec: (b) => [
        ['gml', `<textarea data-p="exec.0" rows="3">${C.esc(b.exec[0] || '')}</textarea>`],
        ['', '<span class="note">passed through verbatim, and replayed on a seek — the compiler cannot tell whether it sets up the world</span>']],
      autosave: () => [['', '<span class="note">saveGame() unless difficulty = Hard</span>']],
      win: () => [['', '<span class="note">missionSucc() — ends the episode</span>']],
      start: () => [['', '<span class="note">runs from alarm[2]; the counter stays 0</span>']],
      wait: () => [],
      pause: (b) => {
        const msg = ('say' in b) || ('objective' in b);
        return [
          ['steps', `<input data-p="pause" data-num value="${b.pause}">`],
          ['', `<span class="note">${(b.pause / 30).toFixed(1)}s at room_speed 30. A silent beat`
            + ' normally hands over with <code>event_user(0)</code>, which re-enters the ladder in the'
            + ' <i>same frame</i> — so anything this beat started is never seen. This holds it on'
            + ' alarm[3] instead.</span>'],
          ...(msg ? [['', '<span class="note stale">this beat shows a message, and a message panel'
            + ' already holds the beat until the player closes it — the pause does nothing here.'
            + ' Put it on a silent beat before this one.</span>']] : []),
        ];
      },
    };

    const ADDABLE = ['note', 'say', 'objective', 'spawn', 'gate', 'camera', 'meteors', 'interference',
      'controls', 'surge', 'bounds', 'music', 'autosave', 'pause', 'win'];

    // Paths whose field may legally be empty, meaning the key is not written.
    const OPTIONAL = /^spawn\.\d+\.(sprite|scale|angle|frame|tint|name)$/;

    function renderIns() {
      const mm = m(), i = App.selected, b = mm.beats[i];
      const n = C.numberBeats(mm)[i], adv = C.advanceOf(b);
      root.querySelector('.ins-h').innerHTML =
        `<div class="n">beat ${i} · rung ${n.n}</div><div class="a">↓ ${adv ? adv.label : '—'}${adv && adv.sub ? ' · ' + adv.sub : ''}</div>`;
      const cards = Object.keys(b).filter((k) => F[k] && k !== 'wait').map((k) => {
        // A null label is a full-width row. The rail is a two-column grid of
        // label/value, which is right for a field and wrong for a divider —
        // `spawn:` is a list and its entries need a strip they can be separated
        // and removed by, at a size a person can hit.
        const rows = F[k](b).map(([l, html]) => (l === null
          ? `<div class="full">${html}</div>`
          : `<label>${l}</label><div>${html}</div>`)).join('');
        return `<div class="card ${k}"><h5>${k}${k === 'start' ? '' : `<span class="x" data-rm="${k}">✕</span>`}</h5>
          ${rows ? `<div class="rows">${rows}</div>` : ''}</div>`;
      }).join('');
      const add = ADDABLE.filter((k) => !(k in b)).map((k) => `<button data-add="${k}">+ ${k}</button>`).join('');
      root.querySelector('.ins-b').innerHTML = cards + `<div class="ins-add">${add}</div>`;
    }

    /* The two DOM trees this module owns — the beat track and the rail — rebuilt
       from the model. No paint: App.change() already emits 'change', and the
       subscriber below paints. Calling both is two full repaints of the same
       state, and a repaint is the map, the ruler, four lanes, the message panel
       and (when the drawer is open) the whole mission re-serialised to YAML. */
    function structure() { renderTrack(); renderIns(); }

    /* structure() plus the paint, for the callers that do *not* go through
       App.change(): mount, and a reload that replaced the mission wholesale. */
    function full() { structure(); TL.paint(refs); }

    /* Refresh the rail's *values* in place, without rebuilding it.
       The rail is rendered from the model on select and on reload, which is
       enough while every edit originates inside it — the DOM already holds what
       you just typed. Dragging a beacon on the map is the first edit that does
       not, and a full renderIns() is the wrong answer twice over: it runs sixty
       times a second during a drag, and it would eat the caret of whatever field
       had focus. So this writes the two things a beacon move changes and skips
       the focused element. */
    function syncFields() {
      const mm = m();
      root.querySelectorAll('[data-gp]').forEach((f) => {
        if (f === document.activeElement) return;
        const [k, axis] = f.dataset.gp.split('.');
        const g = (mm.gates || [])[+k];
        if (g) f.value = g[axis];
      });
      // Everything else in the rail addresses the selected beat by path, which
      // is enough to write it back the same way: a spawn or a gate_at dragged
      // on the map lands in the card without rebuilding it.
      const b = mm.beats[App.selected];
      root.querySelectorAll('[data-p]').forEach((f) => {
        if (f === document.activeElement || !b) return;
        const v = C.getPath(b, f.dataset.p);
        if (v == null || typeof v === 'object') return;
        const s = String(typeof v === 'boolean' ? (v ? 'on' : 'off') : v);
        if (f.value !== s) f.value = s;
      });
      // the beacon picker prints each beacon's position in its option labels
      root.querySelectorAll('select[data-p="gate"] option').forEach((o) => {
        const g = (mm.gates || [])[+o.value];
        if (g) o.textContent = `${+o.value + 1} — (${g.x}, ${g.y})`;
      });
    }

    // ------------------------------------------------------------- editing
    // One snapshot per typing burst, for the rail's fields *only*. `root` is the
    // whole stage, so this listener also sees focusin from the panels floating
    // over the map — and those take their own snapshots, on their own terms. Two
    // snapshots per focus is not a harmless duplicate: tabbing out of the mission
    // sheet's size field commits the resize and then focuses the next field, so
    // the second snapshot records the state *after* the edit and ctrl-Z appears
    // to do nothing.
    root.addEventListener('focusin', (e) => {
      if (!e.target.closest('.ins')) return;
      if (e.target.matches('input,textarea')) M.begin(m());
    });
    root.addEventListener('input', (e) => {
      const gp = e.target.dataset.gp;
      if (gp) {
        const [k, axis] = gp.split('.');
        const g = (m().gates || [])[+k];
        if (!g) return;
        g[axis] = Number(e.target.value) || 0;
        App.change(); renderTrack(); syncFields();
        return;
      }
      // Stored as lines, edited as a paragraph. Not through Model.poke: the
      // path grammar addresses one key, and a note is the whole list at once.
      if (e.target.dataset.note != null) {
        m().beats[App.selected].note = C.noteFrom(e.target.value);
        App.change(); renderTrack();
        return;
      }
      const p = e.target.dataset.p;
      if (!p) return;
      let v = e.target.value;
      // An optional field left empty is the key being absent, not the key being
      // zero — see Model.poke. Only the look block is optional; everything else
      // has always had a value and keeps the old coercion.
      if (OPTIONAL.test(p) && v.trim() === '') {
        M.poke(m(), App.selected, p, undefined);
        App.change(); renderTrack();
        return;
      }
      if (e.target.dataset.num != null) v = Number(v) || 0;
      if (p === 'gate') v = Number(v);
      if (p === 'wait') { if (v === 'none') delete m().beats[App.selected].wait; else M.poke(m(), App.selected, 'wait', 'gate'); }
      // `interference` is not here: its card is checkboxes, not a select, and
      // the change listener above owns it. Coercing it to a boolean would flatten
      // a per-target block back to all-or-nothing.
      else if (p === 'eerie' || p === 'meteors'
               || p === 'controls' || p === 'surge' || p === 'bounds') M.poke(m(), App.selected, p, v === 'on');
      else M.poke(m(), App.selected, p, v);
      App.change(); renderTrack();
    });
    /* A unique GML-safe identifier for a spawn that has none, derived from what
       it is. Names become `global.<gid>_<name>`, so they have to be identifiers
       and they have to be unique across the mission. */
    function nameSpawn(mm, sp) {
      const base = String(C.spawnLabel(sp)).replace(/\.[^.]*$/, '')
        .replace(/[^A-Za-z0-9]+/g, '').replace(/^[0-9]+/, '') || 'prop';
      const taken = Object.keys(C.pingAnchors(mm));
      let n = base.charAt(0).toLowerCase() + base.slice(1), i = 1;
      while (taken.indexOf(n) >= 0) n = base.charAt(0).toLowerCase() + base.slice(1) + (++i);
      sp.name = n;
      return n;
    }

    /* What a ping is attached to. Writing the link is the whole point: a name is
       one copy of the position, a pair is a second one that can fall out of step
       with the first. Unlinking keeps the ping where it currently is rather than
       resetting it, so the choice is reversible without losing the aim. */
    function pingLink(v) {
      const mm = m(), b = mm.beats[App.selected];
      M.begin(mm);
      if (!v) {
        // Unlinking keeps the ping where it is, so the choice is reversible
        // without losing the aim.
        const at = C.pingAt(mm, b)
          || { x: Math.round(mm.room.width / 2), y: Math.round(mm.room.height / 2) };
        b.ping = [at.x, at.y];
      } else if (v.charAt(0) === '#') {
        const [bi, si] = v.slice(1).split(':').map(Number);
        const sp = ((mm.beats[bi] || {}).spawn || [])[si];
        if (!sp) return;
        b.ping = sp.name || nameSpawn(mm, sp);
      } else b.ping = v;
      App.change(); structure();
    }

    root.addEventListener('change', (e) => {
      if (e.target.dataset.pinglink != null) return pingLink(e.target.value);
      /* An interference target. The model keeps whichever form is shortest —
         `on`, `off`, or the block — rather than always writing the block, so
         ticking both boxes gives back the plain `interference: on` an author
         would have typed, and the file does not grow a distinction the mission
         does not make. Core.Interf.write() decides; this only has to hand it
         the new state. */
      const t = e.target.dataset.interf;
      if (t) {
        const b = m().beats[App.selected];
        const st = C.Interf.state(b.interference);
        st[t] = e.target.checked;
        M.set(m(), App.selected, 'interference',
          C.Interf.TARGETS.every((k) => st[k]) ? true
            : C.Interf.TARGETS.every((k) => !st[k]) ? false : st);
        App.change(); renderTrack(); renderIns();
        return;
      }
      if (e.target.matches('select')) { M.begin(m()); renderIns(); }
    });

    /* Every matching sprite in the tree, drawn as itself. */
    function spritePicker(x, y, current, filter, cb) {
      const A = window.Assets;
      if (!A || !A.ok) return App.toast('no game art — the server could not find BattleshipsForever.exe', 'bad');
      const re = new RegExp(filter);
      const names = Object.keys(A.sprites).filter((n) => re.test(n)).sort();
      const el = popup('sprgrid', x, y, 330, 340,
        names.map((n) => `<figure class="${n === current ? 'on' : ''}" data-n="${n}">
        <img src="api/sprite/${encodeURIComponent(n)}?f=0" alt="" loading="lazy">
        <figcaption>${n.replace(/^spr_/, '')}</figcaption></figure>`).join('')
        || '<div class="dim">nothing matches</div>');
      el.addEventListener('click', (ev) => {
        const f = ev.target.closest('figure');
        if (f) { el.remove(); cb(f.dataset.n); }
      });
    }

    function kindMenu(x, y, cb) {
      const el = popup('menu', x, y, 140, 240,
        ['say', 'objective', 'spawn', 'gate', 'camera', 'empty']
          .map((k) => `<button data-k="${k}">new ${k} beat</button>`).join(''));
      el.addEventListener('click', (ev) => { const k = ev.target.dataset.k; if (k) { el.remove(); cb(k); } });
    }

    root.addEventListener('click', (e) => {
      const opick = e.target.closest('[data-opick]');
      if (opick) {
        const k = +opick.dataset.opick;
        const sp = m().beats[App.selected].spawn[k];
        const r = opick.getBoundingClientRect();
        return objectPicker(r.left - 300, r.bottom + 4, sp.object, (pick) => {
          const e = m().beats[App.selected].spawn[k];
          // `object:` and `ship:` are mutually exclusive, so switching kind
          // takes the other key with it — and the look block only means
          // something for an object.
          if (pick && pick.ship) {
            delete e.object;
            C.LOOK_KEYS.forEach((k) => delete e[k]);
            e.ship = pick.ship;
            if (!e.team) e.team = 'ally';
          } else {
            delete e.ship; delete e.team; delete e.hold; delete e.facing;
            e.object = pick;
          }
          App.change(); structure();
        });
      }
      const rms = e.target.dataset.rmspawn;
      if (rms) {
        if (!M.removeSpawn(m(), App.selected, +rms)) return;
        App.change(); structure(); return;
      }
      if (e.target.dataset.addspawn) {
        M.addSpawn(m(), App.selected); App.change(); structure(); return;
      }
      const clr = e.target.dataset.clear;
      if (clr) { M.set(m(), App.selected, clr, undefined); App.change(); structure(); return; }
      const look = e.target.closest('[data-add-look]');
      if (look) {
        const k = +look.dataset.look;
        const sp = m().beats[App.selected].spawn[k];
        const r = look.getBoundingClientRect();
        // Seed the picker with what the object already draws with, so the grid
        // opens on the thing you are replacing rather than at the top of the As.
        const cur = (window.Assets && window.Assets.spriteOf(sp.object)) || '';
        return spritePicker(r.left - 300, r.bottom + 4, cur, '^spr_',
          (n) => { M.set(m(), App.selected, `spawn.${k}.sprite`, n); App.change(); structure(); });
      }
      const pick = e.target.closest('[data-pick]');
      if (pick) {
        const path = pick.dataset.pick;
        const cur = C.getPath(m().beats[App.selected], path);
        const r = pick.getBoundingClientRect();
        return spritePicker(r.left - 300, r.bottom + 4, cur, pick.dataset.filter,
          (n) => { M.set(m(), App.selected, path, n); App.change(); structure(); });
      }
      if (e.target.closest('.blk')) return;      // selected on pointerdown
      const gap = e.target.closest('.gap');
      if (gap) return kindMenu(e.clientX, e.clientY,
        (kind) => { App.select(M.insert(m(), +gap.dataset.at, kind)); App.change(); structure(); });
      const rm = e.target.dataset.rm;
      if (rm) { M.removeAction(m(), App.selected, rm); App.change(); structure(); return; }
      const add = e.target.dataset.add;
      if (add) {
        const r = M.addAction(m(), App.selected, add);
        if (!r.ok) return App.toast(r.why, 'bad');
        App.change(); structure(); return;
      }
      const op = e.target.dataset.op;
      if (op) {
        const i = App.selected;
        if (op === 'before') App.select(M.insert(m(), i, 'say'));
        if (op === 'after') App.select(M.insert(m(), i + 1, 'say'));
        if (op === 'dup') App.select(M.duplicate(m(), i));
        if (op === 'del') {
          if (!M.remove(m(), i)) return App.toast('the start beat cannot be deleted', 'bad');
          App.select(Math.min(i, m().beats.length - 1));
        }
        App.change(); structure();
      }
    });

    // ---- select, and drag a block along the track to reorder
    // Selection happens here rather than on `click`. The preventDefault below is
    // what stops a drag from painting a text selection across the page, and it
    // is not worth depending on exactly which compatibility mouse events survive
    // it — pressing a block is the gesture, so pressing a block is the event.
    let drag = null;
    refs.beats.addEventListener('pointerdown', (e) => {
      const blk = e.target.closest('.blk');
      if (!blk) return;
      e.preventDefault();                       // a block is a handle, not text
      App.select(+blk.dataset.i);
      drag = { i: +blk.dataset.i, x0: e.clientX, el: blk, live: false };
    });
    const onMove = (e) => {
      if (!drag) return;
      if (!drag.live && Math.abs(e.clientX - drag.x0) < 6) return;
      if (!drag.live) TL.drag(true);
      drag.live = true; drag.el.classList.add('drag');
      drag.to = Math.max(1, Math.min(m().beats.length, Math.round(TL.beatAt(refs, e.clientX))));
      refs.beats.querySelectorAll('.gap').forEach((g) => g.classList.toggle('drop', +g.dataset.at === drag.to));
    };
    const onUp = () => {
      if (drag && drag.live && drag.to != null) {
        const to = drag.to > drag.i ? drag.to - 1 : drag.to;
        App.select(M.move(m(), drag.i, to)); App.change(); structure();
      }
      if (drag && drag.live) TL.drag(false);
      drag = null;
    };
    addEventListener('pointermove', onMove);
    addEventListener('pointerup', onUp);

    App.on('fields', syncFields);
    App.on('select', () => { markTrack(); renderIns(); TL.paint(refs); paintShipThumbs(); });
    // paintShipThumbs too: a hull thumbnail is empty until its dump and its
    // art land, and both arrive as a `change`. Unscoped on purpose — an open
    // picker hangs off document.body, not off the rail.
    App.on('change', () => { TL.paint(refs); paintShipThumbs(); });
    // View first: a different mission is a different room, so the zoom it was
    // left at means nothing — and resetting it after the re-render would draw
    // the new room at the old framing once before correcting itself.
    App.on('reload', () => { View.reset(); full(); paintShipThumbs(); });
    App.on('live', () => { markTrack(); TL.paint(refs); });
    new ResizeObserver(() => TL.paint(refs)).observe(refs.cv.parentElement);
    Paint.mount(refs);
    Handles.mount(refs);
    // After both, on purpose: the pan is what neither of them claimed, and it
    // reads their state on the same pointerdown to find that out.
    View.mount(refs);
    MissionPanel.mount(refs);
    full();
    return refs;
  }

  return { css, mount };
})();
