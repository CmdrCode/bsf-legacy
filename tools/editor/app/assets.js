/* Client half of the asset path: the dev server hands over a sprite manifest
 * extracted live from BattleshipsForever.exe, and this fetches frames on demand.
 *
 * Two things here are not optional, both of them traps the design note calls out:
 *
 *  1. Half the game's art is a PALETTE MASK — three shades of grey the engine
 *     multiplies by a colour at draw time. spr_Nebula, spr_Spacestation,
 *     spr_Meteor, spr_Marker and every hull section are masks. Blit one straight
 *     and you get a black box, so masks go through tinted().
 *  2. ORIGINS ARE DATA. spr_MesHQ's origin is (0,0), spr_Rock's is its centre.
 *     Everything is drawn at -ox,-oy, never at -w/2,-h/2.
 *
 * Tints below are the ones the objects set in their own Create events, read out
 * of the decrypted tree — not taste.
 */
window.Assets = (function () {
  'use strict';

  // bfdefault.ini [<team> Colours]; index 0 is the hull default.
  const TEAMS = [[[0, 255, 0], [64, 255, 64], [128, 255, 128]],
  [[0, 255, 255], [64, 128, 128], [128, 196, 196]],
  [[255, 0, 0], [255, 64, 64], [155, 45, 45]],
  [[255, 0, 255], [128, 0, 255], [255, 128, 128]]];

  const TINT = {                     // object -> image_blend / l_colour at create
    MoveToArea: 'rgb(0,255,0)', Marker: 'rgb(0,255,0)',      // image_blend = c_green
    SpaceStation: 'rgb(0,255,255)',                          // l_colour = global.colour[1,0]
    obs_Meteor: 'rgb(255,255,255)',                          // l_colour = c_white
    ter_Nebula: 'rgb(160,190,255)', ter_MegaNebula: 'rgb(160,190,255)',
    ter_Sun: 'rgb(255,235,180)',
  };
  const ALPHA = { ter_Nebula: 0.38, ter_MegaNebula: 0.5, ter_Sun: 0.9 };

  const A = {
    ok: false, sprites: {}, objects: {}, source: null,
    hulls: new Set(),                // object names that are ships, not props
    onload: null,                    // set by the app: called when art arrives
    _img: {}, _tint: new Map(), _ship: {},
  };

  A.init = function () {
    return fetch('api/assets').then((r) => r.json()).then((d) => {
      if (!d.ok) throw new Error(d.why || 'no assets');
      A.ok = true; A.sprites = d.sprites; A.objects = d.objects; A.source = d.source;
      A.hulls = new Set(d.hulls || []);
      return A;
    }).catch((e) => { A.ok = false; A.why = e.message; return A; });
  };

  /* Ship or prop, answered now.
   *
   * The distinction the UI turns on, and the one the sprite manifest cannot
   * make: a ship draws its sections, so its `sprite_index` is spr_Core and
   * every hull in the game shares it. `A.ship()` knows the answer too, but only
   * after a round trip, and a picker listing 600 objects has to decide how to
   * draw each of them before it has fetched any. So the server sends the whole
   * set with the manifest and this is a lookup. */
  A.isShip = (obj) => A.hulls.has(obj);

  /* Lazily fetched frame. Returns null until it has arrived, then repaints. */
  A.img = function (name, frame) {
    frame = frame || 0;
    const s = A.sprites[name];
    if (!s) return null;
    const key = name + '#' + (frame % s.n);
    let im = A._img[key];
    if (im === undefined) {
      im = new Image();
      im.onload = () => { im._ready = true; if (A.onload) A.onload(); };
      im.onerror = () => { A._img[key] = null; };
      im.src = 'api/sprite/' + encodeURIComponent(name) + '?f=' + (frame % s.n);
      A._img[key] = im;
    }
    return im && im._ready ? im : null;
  };

  /* mask × colour, exactly as image_blend does — the one place the composite is
     written. Fill with the colour, `multiply` the art in, then `destination-in`
     to recover the art's own alpha. Three call sites needed this (two here, one
     in ships.js) and three transcriptions of a three-op sequence is three
     chances for one of them to disagree about the order.

     Takes a ready image or canvas and returns a fresh canvas; caching is the
     caller's, because each of them keys it differently. */
  A.maskTint = function (src, w, h, rgb) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const g = c.getContext('2d');
    g.fillStyle = rgb; g.fillRect(0, 0, w, h);
    g.globalCompositeOperation = 'multiply';
    g.drawImage(src, 0, 0);
    g.globalCompositeOperation = 'destination-in';
    g.drawImage(src, 0, 0);
    return c;
  };

  /* Cached per (sprite, frame, rgb). */
  function tinted(name, frame, rgb) {
    const key = name + '#' + frame + '|' + rgb;
    let c = A._tint.get(key);
    if (c) return c;
    const im = A.img(name, frame), s = A.sprites[name];
    if (!im) return null;
    c = A.maskTint(im, s.w, s.h, rgb);
    A._tint.set(key, c);
    return c;
  }
  A.tinted = tinted;

  A.spriteOf = (obj) => A.objects[obj] || null;

  /* Draw one sprite frame with its real origin, in world units.
     opts: {frame, angle (GM degrees, ccw), scale, tint, alpha} */
  A.blit = function (ctx, name, x, y, opts) {
    opts = opts || {};
    const s = A.sprites[name];
    if (!s) return false;
    const f = opts.frame || 0;
    const src = opts.tint ? tinted(name, f % s.n, opts.tint) : A.img(name, f);
    if (!src) return false;
    const k = opts.scale == null ? 1 : opts.scale;
    ctx.save();
    ctx.globalAlpha = opts.alpha == null ? 1 : opts.alpha;
    ctx.translate(x, y);
    if (opts.angle) ctx.rotate(-opts.angle * Math.PI / 180);   // GM angles are ccw
    ctx.scale(k, k);
    ctx.drawImage(src, -s.ox, -s.oy);
    ctx.restore();
    return true;
  };

  /* Draw an object the way the game would: its sprite, its blend, its alpha. */
  A.drawObject = function (ctx, obj, x, y, opts) {
    opts = opts || {};
    const name = A.spriteOf(obj);
    if (!name || !A.sprites[name]) return false;
    // the blend the object sets at create wins; a mask with no declared blend
    // still has to go through white, which is what image_blend defaults to
    return A.blit(ctx, name, x, y, Object.assign({
      tint: TINT[obj] || (A.sprites[name].mask ? 'rgb(255,255,255)' : null),
      alpha: ALPHA[obj],
    }, opts));
  };

  /* Hulls are not in the exe in readable form; the server serves the render-model
     dump when it has one. Returns null until loaded (and never, if there is none). */
  A.ship = function (name) {
    if (name in A._ship) return A._ship[name];
    A._ship[name] = null;
    fetch('api/ship/' + encodeURIComponent(name))
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!d) return;
        d._img = {};
        Object.entries(d.sprites).forEach(([nm, sp]) => {
          const im = new Image();
          im.onload = () => { im._ready = true; if (A.onload) A.onload(); };
          im.src = sp.src;
          d._img[nm] = im;
        });
        A._ship[name] = d;
        if (A.onload) A.onload();
      })
      .catch(() => { });
    return null;
  };

  /* A real hull: every section blitted at its own offset, angle and team shade. */
  A.drawShip = function (ctx, hull, x, y, opts) {
    opts = opts || {};
    const team = opts.team == null ? 0 : opts.team;
    const angle = opts.angle || 0;
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(-angle * Math.PI / 180);
    let drew = 0;
    (hull.sections || []).forEach((sec) => {
      const sp = hull.sprites[sec.sprite], im = hull._img[sec.sprite];
      if (!sp || !im || !im._ready) return;
      const rgb = TEAMS[team][sec.cls == null ? 0 : sec.cls];
      const key = sec.sprite + '|' + rgb + '|' + team;
      let src = A._tint.get(key);
      if (!src) {
        // Unmasked art is already what it should look like — cache the image
        // itself rather than a canvas holding a copy of it.
        src = sp.mask
          ? A.maskTint(im, sp.w * sp.n, sp.h, `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`)
          : im;
        A._tint.set(key, src);
      }
      ctx.save();
      ctx.translate(sec.x, sec.y);
      ctx.rotate(-(sec.angle || 0) * Math.PI / 180);
      ctx.scale(sec.xscale == null ? 1 : sec.xscale, sec.yscale == null ? 1 : sec.yscale);
      ctx.drawImage(src, 0, 0, sp.w, sp.h, -sp.ox, -sp.oy, sp.w, sp.h);
      ctx.restore();
      drew++;
    });
    ctx.restore();
    return drew > 0;
  };

  /* Extent of a hull, in its own units.

     A design file has a bbox because scene.py computes one; a stock hull dump
     does not, so it is measured here — each section's sprite rect carried
     through the same translate/rotate/scale drawShip applies to it, which is
     why the order below is scale, then rotate, then translate. Cached on the
     hull object, since that is what the fetch already hands back. */
  function hullBox(hull) {
    if (hull._box !== undefined) return hull._box;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    (hull.sections || []).forEach((sec) => {
      const sp = hull.sprites[sec.sprite];
      if (!sp) return;
      const a = -(sec.angle || 0) * Math.PI / 180;
      const co = Math.cos(a), si = Math.sin(a);
      const kx = sec.xscale == null ? 1 : sec.xscale;
      const ky = sec.yscale == null ? 1 : sec.yscale;
      [[-sp.ox, -sp.oy], [sp.w - sp.ox, -sp.oy],
        [-sp.ox, sp.h - sp.oy], [sp.w - sp.ox, sp.h - sp.oy]].forEach((c) => {
        const px = c[0] * kx, py = c[1] * ky;
        const x = sec.x + px * co - py * si, y = sec.y + px * si + py * co;
        if (x < x0) x0 = x;
        if (x > x1) x1 = x;
        if (y < y0) y0 = y;
        if (y > y1) y1 = y;
      });
    });
    hull._box = x1 > x0 ? [x0, y0, x1, y1] : null;
    return hull._box;
  }

  /* A hull thumbnail for a ship *object* — the counterpart of Ships.thumb, which
     does the same job for a design file. Returns false until the dump and its
     art have arrived; every caller repaints on A.onload, and a repaint that
     happens twice is free. */
  A.shipThumb = function (canvas, obj, pad, team) {
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const hull = A.ship(obj);
    if (!hull) return false;
    const box = hullBox(hull);
    if (!box) return false;
    const w = Math.max(1, box[2] - box[0]), h = Math.max(1, box[3] - box[1]);
    const m = pad == null ? 4 : pad;
    const k = Math.min((canvas.width - m * 2) / w, (canvas.height - m * 2) / h);
    ctx.save();
    ctx.translate(canvas.width / 2 - ((box[0] + box[2]) / 2) * k,
      canvas.height / 2 - ((box[1] + box[3]) / 2) * k);
    ctx.scale(k, k);
    const drew = A.drawShip(ctx, hull, 0, 0, { team: team || 0 });
    ctx.restore();
    return drew;
  };

  A.TEAMS = TEAMS;
  return A;
})();
