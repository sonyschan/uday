# -*- coding: utf-8 -*-
"""uDAY month/date glyph layers — the generator behind the on-chain art.

Vendored from the /tmp scripts that produced the shipped 96px set
(mkpix35 -> mk64 -> mk96) and the 300px logo (mklogo), collapsed into one
self-contained file so nothing depends on /tmp surviving.

  python3 mkglyphs.py 96  <outdir>    # reproduces the on-chain layers byte-for-byte
  python3 mkglyphs.py 300 <outdir>    # the HD set

Writes <outdir>/month/MM_{corner,center}.png and <outdir>/date/DD_{corner,center}.png
"""
from PIL import Image
import hashlib, os, sys

# 3-4 x 5 bitmap font
F = {
  '0': ('###', '#.#', '#.#', '#.#', '###'),
  '1': ('.#.', '##.', '.#.', '.#.', '###'),
  '2': ('###', '..#', '###', '#..', '###'),
  '3': ('###', '..#', '###', '..#', '###'),
  '4': ('#.#', '#.#', '###', '..#', '..#'),
  '5': ('###', '#..', '###', '..#', '###'),
  '6': ('###', '#..', '###', '#.#', '###'),
  '7': ('###', '..#', '..#', '..#', '..#'),
  '8': ('###', '#.#', '###', '#.#', '###'),
  '9': ('###', '#.#', '###', '..#', '###'),
  'A': ('###', '#.#', '###', '#.#', '#.#'),
  'B': ('##.', '#.#', '##.', '#.#', '##.'),
  'C': ('###', '#..', '#..', '#..', '###'),
  'D': ('##.', '#.#', '#.#', '#.#', '##.'),
  'E': ('###', '#..', '###', '#..', '###'),
  'F': ('###', '#..', '###', '#..', '#..'),
  'G': ('###', '#..', '#.#', '#.#', '###'),
  'H': ('#.#', '#.#', '###', '#.#', '#.#'),
  'I': ('###', '.#.', '.#.', '.#.', '###'),
  'J': ('..#', '..#', '..#', '#.#', '###'),
  'K': ('#.#', '#.#', '##.', '#.#', '#.#'),
  'L': ('#..', '#..', '#..', '#..', '###'),
  'M': ('#..#', '####', '####', '#..#', '#..#'),
  'N': ('#..#', '##.#', '#.##', '#..#', '#..#'),
  'O': ('###', '#.#', '#.#', '#.#', '###'),
  'P': ('###', '#.#', '###', '#..', '#..'),
  'Q': ('###', '#.#', '#.#', '###', '..#'),
  'R': ('###', '#.#', '###', '##.', '#.#'),
  'S': ('###', '#..', '###', '..#', '###'),
  'T': ('###', '.#.', '.#.', '.#.', '.#.'),
  'U': ('#.#', '#.#', '#.#', '#.#', '###'),
  'V': ('#.#', '#.#', '#.#', '#.#', '.#.'),
  'W': ('#..#', '#..#', '####', '####', '#..#'),
  'X': ('#.#', '#.#', '.#.', '#.#', '#.#'),
  'Y': ('#.#', '#.#', '###', '.#.', '.#.'),
  'Z': ('###', '..#', '.#.', '#..', '###'),
}

BLUE   = [(30,52,84,255),(42,68,104,255),(56,88,126,255)]
MOSAIC = [(0x00,0x4f,0xa9,255),(0xc0,0x43,0x2e,255),(0x08,0x6d,0x44,255),
          (0xc7,0x94,0x62,255),(0x40,0x2e,0x8d,255),(0xa4,0x6f,0xb3,255),
          (0x7c,0x87,0x65,255),(0xd2,0x7a,0x2a,255),(0x2f,0x74,0x7a,255)]
CREAM  = (228,212,178,255)     # inner outline — what makes the glyph read on a busy plate
DARK   = (28,22,16,255)        # outer contour

MONTHS = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC']


def pick(pal, key):
    return pal[int(hashlib.md5(key.encode()).hexdigest()[:8], 16) % len(pal)]


def glyph(text, scale, mode, block, canvas, anchor=None, pad=0,
          cx=.5, cy=.5, gap=1, cream=1, dark=1):
    ws = [len(F[c][0]) for c in text if c in F]
    w = sum(ws) + gap*(len(ws)-1); h = 5
    ink = set(); ox = 0
    for ch in text:
        g = F.get(ch)
        if not g: continue
        for y, row in enumerate(g):
            for x, c in enumerate(row):
                if c == '#': ink.add((ox+x, y))
        ox += len(g[0]) + gap
    if   anchor == 'tl': x0, y0 = pad, pad
    elif anchor == 'br': x0, y0 = canvas-pad-w*scale, canvas-pad-h*scale
    else:                x0, y0 = round(cx*canvas - w*scale/2), round(cy*canvas - h*scale/2)

    im = Image.new('RGBA', (canvas, canvas), (0,0,0,0)); px = im.load()
    solid = set()
    for gx, gy in ink:
        for dy in range(scale):
            for dx in range(scale):
                X, Y = x0+gx*scale+dx, y0+gy*scale+dy
                if 0 <= X < canvas and 0 <= Y < canvas: solid.add((X, Y))

    D = lambda s: {(X+dx, Y+dy) for (X, Y) in s for dx in (-1,0,1) for dy in (-1,0,1)}
    r1 = set(solid)
    for _ in range(cream): r1 = D(r1)
    r1 -= solid
    r2 = set(r1 | solid)
    for _ in range(dark): r2 = D(r2)
    r2 -= solid | r1

    for X, Y in r2:
        if 0 <= X < canvas and 0 <= Y < canvas: px[X, Y] = DARK
    for X, Y in r1:
        if 0 <= X < canvas and 0 <= Y < canvas: px[X, Y] = CREAM
    for X, Y in solid:
        px[X, Y] = pick(BLUE if mode == 'blue' else MOSAIC, '%s:%d,%d' % (text, X//block, Y//block))
    return im


# Per-canvas geometry. 96 is the shipped on-chain set; 300 keeps the same
# proportions, with the corner numbers matching the params the logo shipped with.
CFG = {
  96: {
    'month_corner': dict(scale=3, mode='blue',   block=4, anchor='tl', pad=5,  cream=1, dark=1),
    'month_center': dict(scale=4, mode='blue',   block=5, cx=.50, cy=.33,      cream=1, dark=1),
    'date_corner' : dict(scale=3, mode='mosaic', block=4, anchor='br', pad=5,  cream=1, dark=1),
    'date_center' : dict(scale=6, mode='mosaic', block=6, cx=.50, cy=.66,      cream=1, dark=1),
  },
  300: {
    'month_corner': dict(scale=9,  mode='blue',   block=10, anchor='tl', pad=12, cream=3, dark=3),
    'month_center': dict(scale=13, mode='blue',   block=16, cx=.50, cy=.33,      cream=3, dark=3),
    'date_corner' : dict(scale=9,  mode='mosaic', block=11, anchor='br', pad=12, cream=3, dark=3),
    'date_center' : dict(scale=19, mode='mosaic', block=19, cx=.50, cy=.66,      cream=3, dark=3),
  },
}


def build(canvas, out):
    cfg = CFG[canvas]
    for sub in ('month', 'date'):
        os.makedirs(os.path.join(out, sub), exist_ok=True)
    for i, m in enumerate(MONTHS, 1):
        for place in ('corner', 'center'):
            glyph(m, canvas=canvas, **cfg['month_' + place]).save('%s/month/%02d_%s.png' % (out, i, place))
    for d in range(1, 32):
        for place in ('corner', 'center'):
            glyph('%02d' % d, canvas=canvas, **cfg['date_' + place]).save('%s/date/%02d_%s.png' % (out, d, place))
    print('%dpx -> %s  (month 24, date 62)' % (canvas, out))


if __name__ == '__main__':
    build(int(sys.argv[1]), os.path.expanduser(sys.argv[2]))
