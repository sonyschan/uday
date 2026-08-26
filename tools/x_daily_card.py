#!/usr/bin/env python3
"""Compose the daily X card for uDAY.

The image is NOT a generic render — it is the real earliest surviving piece
of today's date, rebuilt from its decoded recipe in data/art-cache.json, the
same recipes the site's day gallery draws from. The text is drawn with the
same pixel font as the on-chain art (tools/mkglyphs.py), so the card and the
piece are visibly the same object.

The uday.gift wordmark is PAINTED INTO THE IMAGE on purpose: X bills a post
containing a URL at $0.200 against $0.015 without one (docs.x.com, 2026), and
its ranking suppresses outbound links anyway. A drawn wordmark is neither.

usage:  python3 tools/x_daily_card.py [MM-DD] [-o out.png]
        (default: today in UTC+8, the same day boundary the gift uses)
"""
import json, os, sys
from datetime import datetime, timezone, timedelta
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mkglyphs import MONTHS, F                        # the on-chain glyph table

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HD = os.path.join(ROOT, "assets", "hd")
SIZE = 1200                     # X renders a square timeline card well
ART = 900                       # 3x the 300px HD layers — integer, never resampled soft
GROUND = (11, 9, 24, 255)       # the site's midnight indigo


WORDMARK = (232, 185, 63, 255)   # the site's gold


def word_w(word, scale, gap=1):
    ws = [len(F[c][0]) for c in word if c in F]
    return (sum(ws) + gap * (len(ws) - 1)) * scale


def draw_text(card, text, scale, cy, space=3, gap=1):
    """Flat pixel lettering, one solid colour, no outline.

    Not glyph() from mkglyphs: that paints every block a different shade and
    wraps it in cream-then-dark contours, which is what makes the month and
    date read as mosaic on a plate. At wordmark size those same touches are
    just noise — the piece is the art, the wordmark only has to be legible.
    F covers 0-9 and A-Z, so the space and the period are placed here."""
    widths, toks = [], []
    for ch in text:
        if ch == " ":
            toks.append((" ", None)); widths.append(space * scale)
        elif ch == ".":
            toks.append((".", None)); widths.append(2 * scale)
        elif ch in F:
            toks.append((ch, F[ch])); widths.append(len(F[ch][0]) * scale + gap * scale)
    total = sum(widths) - gap * scale
    x = round((SIZE - total) / 2)
    y = round(cy * SIZE - (5 * scale) / 2)
    px = card.load()
    def block(bx, by, w, h):
        for dy in range(h):
            for dx in range(w):
                X, Y = bx + dx, by + dy
                if 0 <= X < SIZE and 0 <= Y < SIZE: px[X, Y] = WORDMARK
    for (ch, g), w in zip(toks, widths):
        if ch == ".":
            block(x, y + 4 * scale, scale, scale)      # sits on the baseline
        elif g:
            for ry, row in enumerate(g):
                for rx, c in enumerate(row):
                    if c == "#": block(x + rx * scale, y + ry * scale, scale, scale)
        x += w


def today_key():
    u = datetime.now(timezone(timedelta(hours=8)))
    return u.strftime("%m-%d")


def piece_of(day):
    """The best-dressed surviving piece of `day`, with its decoded recipe.

    Not the earliest: plate and frame are optional layers (80% / 20%), so a
    day's first piece is often two bare glyphs on transparency — legal art,
    but a weak card. This picks the most-layered piece instead, oldest
    winning ties. Still a real piece of that real date, just the one worth
    showing."""
    idx = json.load(open(os.path.join(ROOT, "data", "date-index.json")))
    cache = json.load(open(os.path.join(ROOT, "data", "art-cache.json")))
    alive = [e for e in (idx["days"].get(day) or []) if str(e["id"]) in cache]
    if not alive:
        return None, None, idx
    def rank(e):
        r = cache[str(e["id"])]
        return (-(bool(r.get("p")) + bool(r.get("f"))), e["id"])
    best = sorted(alive, key=rank)[0]
    return best, cache[str(best["id"])], idx


def compose(recipe, month, date):
    """plate -> frame -> month -> date. Order is the contract's; do not reorder."""
    im = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
    place = {"c": "center", "r": "corner"}
    layers = []
    if recipe.get("p"):
        layers.append(("plate", recipe["p"]))
    if recipe.get("f"):
        layers.append(("frame", recipe["f"]))
    layers.append(("month", "%02d_%s" % (month, place[recipe["mp"]])))
    layers.append(("date",  "%02d_%s" % (date,  place[recipe["dp"]])))
    for kind, name in layers:
        path = os.path.join(HD, kind, name + ".png")
        im.alpha_composite(Image.open(path).convert("RGBA"))
    return im


def build(day, out):
    piece, recipe, idx = piece_of(day)
    if not piece or not recipe:
        sys.exit("%s: no revealed piece to draw" % day)
    m, d = int(day[:2]), int(day[3:])

    card = Image.new("RGBA", (SIZE, SIZE), GROUND)
    art = compose(recipe, m, d).resize((ART, ART), Image.NEAREST)   # integer, hard pixels
    card.alpha_composite(art, ((SIZE - ART) // 2, 96))

    label = "%s %02d" % (MONTHS[m - 1], d)
    draw_text(card, "UDAY.GIFT", 7, 0.905)

    card.convert("RGB").save(out)
    holders = len({e["owner"] for e in idx["days"][day]})
    n = len(idx["days"][day])
    print("wrote %s" % out)
    print("  %s  #%d  %s%s%s" % (label, piece["id"], recipe.get("p") or "no plate",
                                 " + " + recipe["f"] if recipe.get("f") else " + no frame",
                                 "  (%d pieces, %d wallets)" % (n, holders)))
    return {"day": day, "label": label, "id": piece["id"], "pieces": n, "wallets": holders}


if __name__ == "__main__":
    argv = sys.argv[1:]
    out = os.path.join(ROOT, "data", "x-card.png")
    if "-o" in argv:
        i = argv.index("-o")
        out = argv[i + 1]
        del argv[i:i + 2]                     # the path is not a date
    args = [a for a in argv if not a.startswith("-")]
    day = args[0] if args else today_key()
    build(day, out)
