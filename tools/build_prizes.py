#!/usr/bin/env python3
"""What is in the prize pot, and what does it look like.

    python3 tools/build_prizes.py            # verify + fetch + write
    python3 tools/build_prizes.py --dry-run  # say what would change

Reads data/prizes-config.json, checks on chain that the prize holder REALLY
holds each listed piece, pulls the art, and writes what the homepage serves:

    data/prizes.json             the manifest the page reads
    data/prizes/<sym>-<id>.png   the art, at its native pixel size

Why a config rather than reading the holder's inventory: the token contracts
expose ownerAssetBackedTokenCount (a number) and isAssetOwner (a yes/no for one
id), but nothing that ENUMERATES what an address holds. Scanning every id up to
supply is 10,000 calls per project. So the config names the pieces and the
chain confirms them — one call each, and the answer that matters.

A piece that fails its ownership check is DROPPED, loudly, not published.
A prize the page advertises and the pot cannot pay is worse than no prize.
"""
import argparse, json, os, re, sys

try:
    import requests                      # urllib fails TLS on stock macOS python
    from PIL import Image
except ImportError:
    sys.exit("pip install requests pillow")

RPC = os.environ.get("ROBINHOOD_RPC_URL",
                     "https://rpc.mainnet.chain.robinhood.com/rpc")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "data", "prizes-config.json")
OUT_JSON = os.path.join(ROOT, "data", "prizes.json")
OUT_DIR = os.path.join(ROOT, "data", "prizes")

# all from `cast sig`
SEL_SYMBOL   = "0x95d89b41"
SEL_REVEAL   = "0xb509d6c4"      # layerReveal()
SEL_ISOWNER  = "0xccd52464"      # isAssetOwner(address,uint256)
SEL_COUNT    = "0x231e776c"      # ownerAssetBackedTokenCount(address)
SEL_SVG      = "0xeb3fbd83"      # generateSvgForAsset(uint256)


def rasterise(svg):
    """The SVG is a grid of 1x1 <rect>s — pixel art written out longhand. Read
    it back as pixels rather than shipping it: 226KB of markup (17KB gzipped)
    becomes an 8KB PNG at the SAME resolution, and the page then upscales by an
    integer factor, which is the only direction pixel art may be scaled.

    Every rect must parse. A partial parse would render a plausible-looking
    picture with holes in it, which is worse than refusing."""
    m = re.search(r"viewBox='0 0 (\d+) (\d+)'", svg)
    if not m:
        return None, "no viewBox"
    W, H = int(m.group(1)), int(m.group(2))
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    px = im.load()
    found = 0
    for r in re.finditer(
            r"<rect x='(-?\d+)' y='(-?\d+)' width='(\d+)' height='(\d+)' fill='#([0-9a-fA-F]{6})'",
            svg):
        x, y, w, h = (int(r.group(i)) for i in (1, 2, 3, 4))
        c = r.group(5)
        rgb = (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), 255)
        for yy in range(max(0, y), min(y + h, H)):
            for xx in range(max(0, x), min(x + w, W)):
                px[xx, yy] = rgb
        found += 1
    total = svg.count("<rect")
    if found != total:
        return None, "parsed %d of %d rects" % (found, total)
    return im, None


def call(to, data):
    try:
        r = requests.post(RPC, timeout=40, json={
            "jsonrpc": "2.0", "id": 1, "method": "eth_call",
            "params": [{"to": to, "data": data}, "latest"]})
        res = r.json().get("result")
        return None if not res or res == "0x" else res
    except Exception:
        return None


def dec_string(h):
    if not h:
        return None
    b = h[2:]
    try:
        if len(b) >= 128 and int(b[:64], 16) == 32:
            n = int(b[64:128], 16)
            return bytes.fromhex(b[128:128 + n * 2]).decode("utf-8", "replace")
        return bytes.fromhex(b[:64]).rstrip(b"\x00").decode("ascii")
    except Exception:
        return None


def pad_addr(a):
    return a[2:].lower().rjust(64, "0")


def pad_uint(n):
    return format(n, "x").rjust(64, "0")


def build(dry):
    cfg = json.load(open(CONFIG))
    holder = cfg["holder"]
    out, dropped = [], []

    for p in cfg["prizes"]:
        token, aid = p["token"], int(p["assetId"])
        sym = dec_string(call(token, SEL_SYMBOL)) or "?"
        tag = "%s #%d" % (sym, aid)

        owned = call(token, SEL_ISOWNER + pad_addr(holder) + pad_uint(aid))
        if not owned or int(owned, 16) != 1:
            dropped.append("%s — %s does not hold it" % (tag, holder[:10]))
            continue

        reveal = call(token, SEL_REVEAL)
        reveal = "0x" + reveal[-40:] if reveal else None
        if not reveal or int(reveal, 16) == 0:
            dropped.append("%s — no layerReveal, this token has no art" % tag)
            continue

        svg = dec_string(call(reveal, SEL_SVG + pad_uint(aid)))
        if not svg or "<svg" not in svg:
            dropped.append("%s — the art did not come back" % tag)
            continue

        im, err = rasterise(svg)
        if err:
            dropped.append("%s — could not read the art (%s)" % (tag, err))
            continue

        name = "%s-%d.png" % (re.sub(r"[^a-z0-9]", "", sym.lower()) or "token", aid)
        out.append({"token": token, "assetId": aid, "symbol": sym,
                    "art": "/data/prizes/" + name, "w": im.width, "h": im.height,
                    "note": p.get("note", ""), "_im": im, "_file": name})
        print("  ok    %-16s %dx%d  svg %s -> png" % (tag, im.width, im.height,
                                                      "{:,}".format(len(svg))))

    for d in dropped:
        print("  DROP  " + d)

    manifest = {"holder": holder,
                "drawAt": cfg.get("drawAt"),
                "prizes": [{k: v for k, v in p.items() if not k.startswith("_")} for p in out]}

    if dry:
        print("\n  --dry-run: nothing written")
        return len(out)

    os.makedirs(OUT_DIR, exist_ok=True)
    keep = set()
    for p in out:
        p["_im"].save(os.path.join(OUT_DIR, p["_file"]), "PNG", optimize=True)
        keep.add(p["_file"])
    # a piece that left the pot must stop being served, not linger as a file
    for f in os.listdir(OUT_DIR):
        if f.endswith(".png") and f not in keep:
            os.remove(os.path.join(OUT_DIR, f))
            print("  removed stale %s" % f)
    json.dump(manifest, open(OUT_JSON, "w"), indent=1, ensure_ascii=False)
    print("\n  wrote %s (%d prize%s)" % (os.path.relpath(OUT_JSON, ROOT),
                                         len(out), "" if len(out) == 1 else "s"))
    return len(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not os.path.exists(CONFIG):
        sys.exit("no %s" % os.path.relpath(CONFIG, ROOT))
    n = build(a.dry_run)
    # zero prizes is a valid state — the pot is empty and the page hides the
    # block — so it is not an error. A DROP already printed loudly above.
    sys.exit(0)
