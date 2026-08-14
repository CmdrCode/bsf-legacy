/* Ship designs: the hulls a mission can spawn from a file.
 *
 * A stock hull is a Game Maker *object* and the object picker already reaches
 * it. This is for the ones that exist only as files — the campaign's own under
 * `mods/ships/`, and the eight the game ships in `Custom Ships/` — which a
 * mission names by path and the game loads with `importShip`.
 *
 * The geometry is not computed here. The server hands over the same draw list
 * that `tools/bsf`'s PIL renderer and `ship serve` consume, built once in
 * scene.py, so the map cannot disagree with them about depth order, mirroring
 * or where a turret pivots. What this module owns is the blit: loading each
 * sprite, tinting the masked ones, and drawing the list in world units.
 *
 * Sprite bytes come from the server as ordinary PNGs off the install's
 * `Custom sprites/`. That is the whole reason the editor takes a dependency on
 * scene.py's *geometry* and not on tools/bsf's art pipeline: that pipeline
 * caches extracted frames on disk, and this process writes nothing.
 */
window.Ships = (function () {
  'use strict';

  const S = {
    list: [],           // [{file, root, name, title, generation, sections, mounts, stale}]
    byFile: {},
    scenes: {},         // file -> scene | 'loading' | null
    imgs: {},           // url  -> Image
    tint: new Map(),
    onload: null,       // called when anything new finishes loading
  };

  /* Rescan. Cheap — a directory listing and a parse per ship — and done on
     demand rather than once at startup, because exporting a ship from
     ShipMaker is something that happens while the editor is open. */
  function refresh() {
    return fetch('api/ships').then((r) => r.json()).then((d) => {
      S.list = (d && d.ships) || [];
      S.byFile = {};
      S.list.forEach((s) => { S.byFile[s.file] = s; });
      return S.list;
    }).catch(() => S.list);
  }

  function info(file) { return S.byFile[file] || null; }

  /* The draw list for one design. Returns null until it has arrived; every
     caller here is a repaint, and a repaint that happens again is free. */
  function scene(file) {
    if (file in S.scenes) return S.scenes[file] === 'loading' ? null : S.scenes[file];
    S.scenes[file] = 'loading';
    fetch('api/shipscene?f=' + encodeURIComponent(file))
      .then((r) => r.json())
      .then((d) => {
        S.scenes[file] = d && d.ok ? d.scene : null;
        if (d && d.ok) d.scene.ops.forEach((o) => image(o.spr));
        if (S.onload) S.onload();
      })
      .catch(() => { S.scenes[file] = null; });
    return null;
  }

  function image(url) {
    let im = S.imgs[url];
    if (im) return im._ready ? im : null;
    im = new Image();
    im.onload = () => { im._ready = true; if (S.onload) S.onload(); };
    im.src = url;
    S.imgs[url] = im;
    return null;
  }

  /* Ship art is not the exe's art, and it does not carry alpha.
   *
   * `Custom sprites/*.png` are palette PNGs with **no transparency**: every
   * pixel is opaque and the empty area is plain black. The game hides it by
   * multiplying the sprite with the team colour, so black stays black against
   * space — but a canvas blit paints an opaque 80x80 square, and twenty
   * sections paint a black slab over the map.
   *
   * So the key is recovered the way tools/bsf/sprites.py does it, which is the
   * way Game Maker does it: **the bottom-left pixel is the transparency key**,
   * and anything equal to it is invisible. A mask is then flattened to the same
   * two shades the PIL renderer uses (47 fill, 255 edge, split at 140), so the
   * map and `ship render` produce the same picture rather than merely similar
   * ones.
   */
  const MASK_FILL = 47, MASK_EDGE = 255, MASK_SPLIT = 140;

  function tinted(url, rgb, w, h, mask) {
    const ck = url + '|' + (mask ? rgb : '-');
    let c = S.tint.get(ck);
    if (c) return c;
    const im = S.imgs[url];
    if (!im || !im._ready) return null;

    const src = document.createElement('canvas');
    src.width = w; src.height = h;
    const sg = src.getContext('2d', { willReadFrequently: true });
    sg.drawImage(im, 0, 0);
    const d = sg.getImageData(0, 0, w, h);
    const p = d.data;
    const kb = ((h - 1) * w) * 4;                 // bottom-left pixel: GM's key
    const kr = p[kb], kg = p[kb + 1], kk = p[kb + 2];
    for (let i = 0; i < p.length; i += 4) {
      if (p[i] === kr && p[i + 1] === kg && p[i + 2] === kk) { p[i + 3] = 0; continue; }
      if (!mask) continue;
      const v = (p[i] + p[i + 1] + p[i + 2]) / 3 > MASK_SPLIT ? MASK_EDGE : MASK_FILL;
      p[i] = p[i + 1] = p[i + 2] = v;
    }
    sg.putImageData(d, 0, 0);

    if (!mask) { S.tint.set(ck, src); return src; }
    c = Assets.maskTint(src, w, h, rgb);          // the one image_blend composite
    S.tint.set(ck, c);
    return c;
  }

  /* Draw a design at a world position. `world` runs its callback under the
     map's own scale, so everything inside is in world units — the same
     convention Assets.blit uses, and the reason a ship lines up with the
     beacons around it without a second transform.

     Returns false if nothing could be drawn yet, so the caller can fall back
     to a placeholder rather than leaving a hole. */
  function draw(ctx, file, wx, wy, opts) {
    opts = opts || {};
    const sc = scene(file);
    if (!sc) return false;
    let drew = false;
    ctx.save();
    ctx.translate(wx, wy);
    if (opts.angle) ctx.rotate(-opts.angle * Math.PI / 180);   // GM angles are ccw
    if (opts.scale && opts.scale !== 1) ctx.scale(opts.scale, opts.scale);
    ctx.globalAlpha = opts.alpha == null ? 1 : opts.alpha;
    sc.ops.forEach((o) => {
      const im = image(o.spr);
      if (!im) return;
      // Everything goes through the keyer, mask or not: none of this art
      // carries alpha, so an unkeyed blit is an opaque rectangle either way.
      const src = tinted(o.spr, opts.tint || o.blend, o.w, o.h, o.mask);
      if (!src) return;
      ctx.save();
      ctx.globalAlpha *= o.alpha == null ? 1 : o.alpha;
      ctx.translate(o.x, o.y);
      if (o.ang) ctx.rotate(-o.ang * Math.PI / 180);
      ctx.scale(o.xs, o.ys);
      ctx.drawImage(src, -o.ox, -o.oy);
      ctx.restore();
      drew = true;
    });
    ctx.restore();
    return drew;
  }

  /* Half-extent in world units, for a placeholder box and for hit testing. */
  function radius(file) {
    const sc = scene(file);
    if (!sc || !sc.bbox) return 60;
    const [x0, y0, x1, y1] = sc.bbox;
    return Math.max(Math.abs(x0), Math.abs(x1), Math.abs(y0), Math.abs(y1)) || 60;
  }

  /* A thumbnail for the picker, drawn from the same list, scaled to fit. */
  function thumb(canvas, file, pad) {
    const sc = scene(file);
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!sc || !sc.bbox) return false;
    const [x0, y0, x1, y1] = sc.bbox;
    const w = Math.max(1, x1 - x0), h = Math.max(1, y1 - y0);
    const m = pad == null ? 4 : pad;
    const k = Math.min((canvas.width - m * 2) / w, (canvas.height - m * 2) / h);
    ctx.save();
    ctx.translate(canvas.width / 2 - ((x0 + x1) / 2) * k,
      canvas.height / 2 - ((y0 + y1) / 2) * k);
    ctx.scale(k, k);
    const drew = draw(ctx, file, 0, 0, {});
    ctx.restore();
    return drew;
  }

  return { refresh, info, scene, draw, thumb, radius, state: S };
})();
