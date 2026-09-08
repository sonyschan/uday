// The share card for one piece: GET /card/<assetId>.png  (rewritten to /api/card?id=)
//
// Why a function and not a file: X reads the card image from og:image and
// runs no JavaScript, so "share MY piece" needs a real PNG at a real URL for
// every piece a holder might share. Pre-rendering one per dated piece would
// put tens of megabytes into the repo and grow with every reveal; rendering
// on demand and letting the CDN keep it (traits never change after reveal,
// so the image is immutable) costs nothing at rest.
//
// Zero dependencies on purpose. The four layers are 300x300 8-bit RGBA PNGs,
// which is the one PNG shape this decoder handles; the composite is
// plate -> frame -> month -> date, the contract's order, scaled 2x with
// nearest-neighbour so the pixels stay hard. Text is the on-chain glyph
// table from tools/mkglyphs.py, not a font, so the card and the art are
// visibly the same object.
import { readFileSync } from 'node:fs';
import { inflateSync, deflateSync } from 'node:zlib';
import { join } from 'node:path';
import cache from '../data/art-cache.json' with { type: 'json' };

const HD = join(process.cwd(), 'assets', 'hd');
const W = 1200, H = 630;
const GROUND = [11, 9, 24];            // the site's midnight indigo
const GOLD = [232, 185, 63];
const CREAM = [244, 240, 230];
const MONTHS = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
const F = {"0":["###","#.#","#.#","#.#","###"],"1":[".#.","##.",".#.",".#.","###"],"2":["###","..#","###","#..","###"],"3":["###","..#","###","..#","###"],"4":["#.#","#.#","###","..#","..#"],"5":["###","#..","###","..#","###"],"6":["###","#..","###","#.#","###"],"7":["###","..#","..#","..#","..#"],"8":["###","#.#","###","#.#","###"],"9":["###","#.#","###","..#","###"],"A":["###","#.#","###","#.#","#.#"],"B":["##.","#.#","##.","#.#","##."],"C":["###","#..","#..","#..","###"],"D":["##.","#.#","#.#","#.#","##."],"E":["###","#..","###","#..","###"],"F":["###","#..","###","#..","#.."],"G":["###","#..","#.#","#.#","###"],"H":["#.#","#.#","###","#.#","#.#"],"I":["###",".#.",".#.",".#.","###"],"J":["..#","..#","..#","#.#","###"],"K":["#.#","#.#","##.","#.#","#.#"],"L":["#..","#..","#..","#..","###"],"M":["#..#","####","####","#..#","#..#"],"N":["#..#","##.#","#.##","#..#","#..#"],"O":["###","#.#","#.#","#.#","###"],"P":["###","#.#","###","#..","#.."],"Q":["###","#.#","#.#","###","..#"],"R":["###","#.#","###","##.","#.#"],"S":["###","#..","###","..#","###"],"T":["###",".#.",".#.",".#.",".#."],"U":["#.#","#.#","#.#","#.#","###"],"V":["#.#","#.#","#.#","#.#",".#."],"W":["#..#","#..#","####","####","#..#"],"X":["#.#","#.#",".#.","#.#","#.#"],"Y":["#.#","#.#","###",".#.",".#."],"Z":["###","..#",".#.","#..","###"]};

// ---- PNG in ---------------------------------------------------------------
function readPng(path) {
  const b = readFileSync(path);
  let p = 8, w = 0, h = 0; const idat = [];
  while (p < b.length) {
    const len = b.readUInt32BE(p), type = b.toString('ascii', p + 4, p + 8);
    const body = b.subarray(p + 8, p + 8 + len);
    if (type === 'IHDR') {
      w = body.readUInt32BE(0); h = body.readUInt32BE(4);
      if (body[8] !== 8 || body[9] !== 6 || body[12] !== 0)
        throw new Error('layer is not 8-bit RGBA non-interlaced: ' + path);
    } else if (type === 'IDAT') idat.push(body);
    p += 12 + len;
  }
  const raw = inflateSync(Buffer.concat(idat));
  const bpp = 4, stride = w * bpp, out = Buffer.alloc(stride * h);
  let s = 0;
  for (let y = 0; y < h; y++) {
    const f = raw[s++], row = y * stride, prev = row - stride;
    for (let x = 0; x < stride; x++) {
      const a = x >= bpp ? out[row + x - bpp] : 0;
      const bb = y > 0 ? out[prev + x] : 0;
      const c = (y > 0 && x >= bpp) ? out[prev + x - bpp] : 0;
      let v = raw[s++];
      if (f === 1) v += a;
      else if (f === 2) v += bb;
      else if (f === 3) v += (a + bb) >> 1;
      else if (f === 4) { const pp = a + bb - c, pa = Math.abs(pp - a), pb = Math.abs(pp - bb), pc = Math.abs(pp - c); v += (pa <= pb && pa <= pc) ? a : (pb <= pc ? bb : c); }
      out[row + x] = v & 255;
    }
  }
  return { w, h, px: out };
}

// ---- PNG out --------------------------------------------------------------
const CRC = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
function crc32(buf) { let c = 0xffffffff; for (let i = 0; i < buf.length; i++) c = CRC[(c ^ buf[i]) & 255] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; }
function chunk(type, body) {
  const out = Buffer.alloc(12 + body.length);
  out.writeUInt32BE(body.length, 0); out.write(type, 4, 'ascii'); body.copy(out, 8);
  out.writeUInt32BE(crc32(out.subarray(4, 8 + body.length)), 8 + body.length);
  return out;
}
function writePng(w, h, rgb) {
  const raw = Buffer.alloc((w * 3 + 1) * h);
  for (let y = 0; y < h; y++) { raw[y * (w * 3 + 1)] = 0; rgb.copy(raw, y * (w * 3 + 1) + 1, y * w * 3, (y + 1) * w * 3); }
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 2;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', deflateSync(raw, { level: 9 })), chunk('IEND', Buffer.alloc(0))]);
}

// ---- drawing --------------------------------------------------------------
function ground() {
  const rgb = Buffer.alloc(W * H * 3);
  for (let i = 0; i < W * H; i++) { rgb[i * 3] = GROUND[0]; rgb[i * 3 + 1] = GROUND[1]; rgb[i * 3 + 2] = GROUND[2]; }
  return rgb;
}
/// Alpha-composite a 300px RGBA layer onto the card at integer scale.
function blit(rgb, layer, ox, oy, scale) {
  for (let y = 0; y < layer.h; y++) for (let x = 0; x < layer.w; x++) {
    const i = (y * layer.w + x) * 4, a = layer.px[i + 3];
    if (!a) continue;
    for (let dy = 0; dy < scale; dy++) for (let dx = 0; dx < scale; dx++) {
      const X = ox + x * scale + dx, Y = oy + y * scale + dy;
      if (X < 0 || Y < 0 || X >= W || Y >= H) continue;
      const o = (Y * W + X) * 3;
      for (let c = 0; c < 3; c++) rgb[o + c] = (layer.px[i + c] * a + rgb[o + c] * (255 - a) + 127) / 255 | 0;
    }
  }
}
function block(rgb, bx, by, w, h, col) {
  for (let y = by; y < by + h; y++) for (let x = bx; x < bx + w; x++) {
    if (x < 0 || y < 0 || x >= W || y >= H) continue;
    const o = (y * W + x) * 3; rgb[o] = col[0]; rgb[o + 1] = col[1]; rgb[o + 2] = col[2];
  }
}
/// Flat pixel lettering from the glyph table, same as the X daily card.
function textWidth(text, scale) {
  let w = 0;
  for (const ch of text) w += ch === ' ' ? 3 * scale : ch === '.' ? 2 * scale : ch === '#' ? 6 * scale : (F[ch] ? (F[ch][0].length + 1) * scale : 0);
  return w - scale;
}
function drawText(rgb, text, scale, cx, cy, col) {
  let x = Math.round(cx - textWidth(text, scale) / 2), y = Math.round(cy - 2.5 * scale);
  for (const ch of text) {
    if (ch === ' ') { x += 3 * scale; continue; }
    if (ch === '.') { block(rgb, x, y + 4 * scale, scale, scale, col); x += 2 * scale; continue; }
    if (ch === '#') { // not in the on-chain table: a hash drawn by hand, 5 wide
      ['.#.#.', '#####', '.#.#.', '#####', '.#.#.'].forEach((row, ry) => [...row].forEach((c, rx) => { if (c === '#') block(rgb, x + rx * scale, y + ry * scale, scale, scale, col); }));
      x += 6 * scale; continue;
    }
    const g = F[ch]; if (!g) continue;
    g.forEach((row, ry) => [...row].forEach((c, rx) => { if (c === '#') block(rgb, x + rx * scale, y + ry * scale, scale, scale, col); }));
    x += (g[0].length + 1) * scale;
  }
}

export function renderCard(id) {
  const r = cache[String(id)];
  if (!r || !r.d) return null;
  const m = +r.d.slice(0, 2), d = +r.d.slice(3);
  const place = { c: 'center', r: 'corner' };
  const layers = [];
  if (r.p) layers.push(['plate', r.p]);
  if (r.f) layers.push(['frame', r.f]);
  layers.push(['month', String(m).padStart(2, '0') + '_' + place[r.mp]]);
  layers.push(['date', String(d).padStart(2, '0') + '_' + place[r.dp]]);

  const rgb = ground();
  const ART = 600, ax = 70, ay = (H - ART) >> 1;          // 2x, integer, hard pixels
  for (const [kind, name] of layers) blit(rgb, readPng(join(HD, kind, name + '.png')), ax, ay, 2);

  const cx = ax + ART + (W - ax - ART) / 2;              // the text column, centred in what is left
  drawText(rgb, MONTHS[m - 1] + ' ' + String(d).padStart(2, '0'), 13, cx, 250, CREAM);
  drawText(rgb, 'UDAY #' + id, 6, cx, 350, GOLD);
  drawText(rgb, 'UDAY.GIFT', 5, cx, 555, GOLD);
  return writePng(W, H, rgb);
}

export default function handler(req, res) {
  const id = String(req.query.id || '').replace(/\.png$/, '');
  if (!/^\d{1,7}$/.test(id)) { res.statusCode = 400; return res.end('bad id'); }
  const png = renderCard(id);
  if (!png) { res.statusCode = 404; res.setHeader('Cache-Control', 'public, s-maxage=600'); return res.end('no such dated piece'); }
  res.setHeader('Content-Type', 'image/png');
  // traits are fixed once revealed, so the image for an id never changes
  res.setHeader('Cache-Control', 'public, max-age=86400, s-maxage=31536000, immutable');
  res.end(png);
}
