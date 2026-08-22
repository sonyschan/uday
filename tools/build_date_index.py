# -*- coding: utf-8 -*-
"""uDAY date index builder — the only date search that can exist for uDAY.

uToken's own metadata cannot tell AUG 22 from JAN 01 (its trait names for the
month/date layers are just "Center"/"Corner"), so the date identity lives ONLY
in the on-chain element indices. This script reads them and publishes
data/date-index.json, which the site serves statically — visitors never touch
the RPC.

Contracts (Robinhood Chain, id 4663):
  token          0x359211bb6b8cabce02dcbec1c55b50f2ec884146
  reveal/render  0x9815c074cba26707e0baa29efdf13f31ee8d27d8
                 (found via the launch-tx receipt; generateLayerElement /
                  generateAppearanceSeed / generateSvg(seed) live here)

Usage:
  python3 tools/build_date_index.py calibrate   # once; writes tools/element_map.json
  python3 tools/build_date_index.py build       # writes data/date-index.json

Calibration maps raw element indices -> (month, day, placement) by rendering
generateSvg(seed) for exemplar assets and pixel-matching the pure-<rect> SVG
against our own 96px layer PNGs (assets/layers/** — byte-identical to what was
uploaded on-chain). No guessing: an element order hypothesis died twice before
this approach (desc-order fit month but not date), so labels come only from
rendered pixels. The build refuses to publish if spot checks fail.

Stdlib + PIL only. Selectors are hardcoded (no keccak in stdlib):
  generateLayerElement(uint256,uint8)  0x3979c4c3
  generateAppearanceSeed(uint256)      0xd38d9dd3
  generateSvg(uint256)                 0xbc921dc2
"""
import json, os, re, ssl, sys, time, urllib.request

# python.org macOS builds ship without system CA certs; try certifi, then the
# OS bundle. CI (ubuntu) never hits this.
def _ssl_ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        for ca in ("/etc/ssl/cert.pem", "/private/etc/ssl/cert.pem"):
            if os.path.exists(ca):
                return ssl.create_default_context(cafile=ca)
    return ssl.create_default_context()

_CTX = _ssl_ctx()

UA = {"User-Agent": "Mozilla/5.0 (uday.gift index builder)"}

def urlopen(req, timeout=45):
    # utoken's WAF 403s the default Python-urllib UA
    if isinstance(req, str):
        req = urllib.request.Request(req, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout, context=_CTX)

ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RPCS     = ["https://rpc.mainnet.chain.robinhood.com",
            "https://rpc.mainnet.chain.robinhood.com/rpc"]   # same node, both shapes
TOKEN    = "0x359211bb6b8cabce02dcbec1c55b50f2ec884146"
RENDERER = "0x9815c074cba26707e0baa29efdf13f31ee8d27d8"
API      = f"https://utoken.so/api/tokens/{TOKEN}"
SEL_ELEM = "0x3979c4c3"
SEL_SEED = "0xd38d9dd3"
SEL_SVG  = "0xbc921dc2"
L_MONTH, L_DATE = 3, 4          # getLayerNames() = ["", Plate, Frame, Month, Date]
MAP_PATH   = os.path.join(ROOT, "tools", "element_map.json")
CACHE_PATH = os.path.join(ROOT, "data", "element-cache.json")
INDEX_PATH = os.path.join(ROOT, "data", "date-index.json")
LAYER_DIR  = os.path.join(ROOT, "assets", "layers")


# ── JSON-RPC with retries (the public RPC flaps; a builder just retries) ──────
def rpc(payload, tries=10):
    body = json.dumps(payload).encode()
    last = None
    for attempt in range(tries):
        url = RPCS[attempt % len(RPCS)]
        try:
            req = urllib.request.Request(url, body, {"Content-Type": "application/json", **UA})
            with urlopen(req) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last = e
            # the public node rate-limits; 429 needs patience, not speed
            time.sleep(45 if e.code == 429 else 3 * (attempt + 1))
        except Exception as e:               # noqa: BLE001 - retrying is the point
            last = e
            time.sleep(3 * (attempt + 1))
    raise SystemExit(f"RPC dead after {tries} tries: {last}")


def eth_call(to, data):
    out = rpc({"jsonrpc": "2.0", "id": 1, "method": "eth_call",
               "params": [{"to": to, "data": data}, "latest"]})
    if "error" in out:
        raise RuntimeError(out["error"])
    return out["result"]


def eth_call_batch(calls):
    """calls: [(to, data)] -> [result_hex|None]. Falls back to singles if the
    node rejects batches."""
    payload = [{"jsonrpc": "2.0", "id": i, "method": "eth_call",
                "params": [{"to": t, "data": d}, "latest"]}
               for i, (t, d) in enumerate(calls)]
    out = rpc(payload)
    if isinstance(out, list):
        res = [None] * len(calls)
        for o in out:
            if "result" in o:
                res[o["id"]] = o["result"]
        return res
    return [eth_call(t, d) for t, d in calls]        # batch unsupported


def u256(n):
    return format(n, "064x")


def call_elem(asset, layer):
    return int(eth_call(RENDERER, SEL_ELEM + u256(asset) + u256(layer)), 16)


def call_seed(asset):
    return int(eth_call(RENDERER, SEL_SEED + u256(asset)), 16)


def call_svg(seed):
    raw = eth_call(RENDERER, SEL_SVG + u256(seed))
    b = bytes.fromhex(raw[2:])
    ln = int.from_bytes(b[32:64], "big")
    return b[64:64 + ln].decode()


# ── rect-SVG rasterizer (the chain art is a pure <rect> grid; no browser) ─────
RECT = re.compile(r"<rect x='(\d+)' y='(\d+)' width='(\d+)' height='(\d+)' fill='(#[0-9a-fA-F]{3,6})'")


def raster(svg):
    from PIL import Image
    im = Image.new("RGB", (96, 96), (0, 0, 0))
    px = im.load()
    for m in RECT.finditer(svg):
        x, y, w, h, f = int(m[1]), int(m[2]), int(m[3]), int(m[4]), m[5]
        if len(f) == 4:
            f = "#" + "".join(c * 2 for c in f[1:])
        col = tuple(int(f[i:i + 2], 16) for i in (1, 3, 5))
        for yy in range(y, min(y + h, 96)):
            for xx in range(x, min(x + w, 96)):
                px[xx, yy] = col
    return im


def layer_pngs(sub):
    from PIL import Image
    out = {}
    d = os.path.join(LAYER_DIR, sub)
    for fn in sorted(os.listdir(d)):
        if fn.endswith(".png"):
            out[fn[:-4]] = Image.open(os.path.join(d, fn)).convert("RGBA")
    return out


def match_glyph(composite, candidates, exclude=None):
    """Which candidate PNG's opaque pixels appear verbatim in the composite?
    `exclude`: opaque region painted AFTER this layer (the date layer overdraws
    the month layer), skipped during comparison."""
    px = composite.load()
    best = None
    for name, im in candidates.items():
        cp = im.load()
        ok = checked = 0
        for y in range(96):
            for x in range(96):
                c = cp[x, y]
                if c[3] < 250:
                    continue
                if exclude and exclude[x, y][3] >= 250:
                    continue
                checked += 1
                if px[x, y] == c[:3]:
                    ok += 1
        if checked and ok / checked > 0.995:
            if best is not None:
                raise RuntimeError(f"ambiguous match: {best} vs {name}")
            best = name
    return best


# ── uToken API: live asset list (ids + owners); burns fall out for free ──────
def fetch_assets():
    items, page = [], 1
    while True:
        with urlopen(f"{API}/assets?limit=60&page={page}", timeout=30) as r:
            d = json.loads(r.read())
        items += [(int(i["assetId"]), i["owner"]) for i in d["items"]]
        if page >= d.get("pageCount") or not d["items"]:
            break
        page += 1
    return items


def load_cache():
    try:
        return {int(k): v for k, v in json.load(open(CACHE_PATH)).items()}
    except FileNotFoundError:
        return {}


def elements_for(ids):
    """assetId -> [month_elem, date_elem]. Traits are fixed once generated
    (owner-confirmed, uPEG-family behaviour), so cached values are immutable —
    only ids never seen before hit the RPC. Burned ids simply stop being asked
    about; the cache keeps their rows harmlessly."""
    cache = load_cache()
    todo = [a for a in ids if a not in cache]
    if not todo:
        return cache

    def flush():
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        tmp = CACHE_PATH + ".tmp"
        json.dump({str(k): v for k, v in sorted(cache.items())}, open(tmp, "w"),
                  separators=(",", ":"))
        os.replace(tmp, CACHE_PATH)

    # 2 reads per id, batched; the cache is CHECKPOINTED as it grows so a
    # flaky-RPC death mid-sweep costs one chunk, not the whole run.
    CH = 30          # ids per chunk = 60 calls; bigger batches earn 429s
    for i in range(0, len(todo), CH):
        part = todo[i:i + CH]
        calls = [(RENDERER, SEL_ELEM + u256(a) + u256(L)) for a in part for L in (L_MONTH, L_DATE)]
        got = eth_call_batch(calls)
        for k, a in enumerate(part):
            me, de = got[2 * k], got[2 * k + 1]
            if me is not None and de is not None:
                cache[a] = [int(me, 16), int(de, 16)]
        flush()
        time.sleep(0.6)
        if (i // CH) % 5 == 0:
            print(f"  ids {min(i+CH,len(todo))}/{len(todo)}")
    return cache


# ── calibrate ────────────────────────────────────────────────────────────────
def calibrate():
    assets = fetch_assets()
    ids = [a for a, _ in assets]
    print(f"{len(ids)} live assets")

    cache = elements_for(ids)
    elems = {a: {L_MONTH: v[0], L_DATE: v[1]} for a, v in cache.items()}

    months = layer_pngs("month")
    dates = layer_pngs("date")
    mmap, dmap = {}, {}
    # one exemplar asset per distinct element value; label it from rendered art
    for a in ids:
        me, de = elems[a][L_MONTH], elems[a][L_DATE]
        if me is None or de is None or (str(me) in mmap and str(de) in dmap):
            continue
        svg = call_svg(call_seed(a))
        comp = raster(svg)
        dhit = match_glyph(comp, dates)                 # date paints last: exact
        if dhit is None:
            continue
        mhit = match_glyph(comp, months, exclude=dates[dhit].load())
        if str(de) not in dmap and dhit:
            dmap[str(de)] = dhit
            print(f"  date elem {de:>3} = {dhit}   (asset {a})")
        if str(me) not in mmap and mhit:
            mmap[str(me)] = mhit
            print(f"  month elem {me:>3} = {mhit}  (asset {a})")
        if len(mmap) >= 24 and len(dmap) >= 62:
            break

    os.makedirs(os.path.dirname(MAP_PATH), exist_ok=True)
    json.dump({"month": mmap, "date": dmap}, open(MAP_PATH, "w"), indent=1, sort_keys=True)
    print(f"wrote {MAP_PATH}: {len(mmap)} month elems, {len(dmap)} date elems")


# ── build ────────────────────────────────────────────────────────────────────
def build():
    emap = json.load(open(MAP_PATH))
    assets = fetch_assets()
    ids = [a for a, _ in assets]
    owner = dict(assets)
    print(f"{len(ids)} live assets")

    cache = elements_for(ids)

    index, unmapped = {}, set()
    for a in ids:
        if a not in cache:
            continue
        me, de = cache[a]
        mn = emap["month"].get(str(me))
        dn = emap["date"].get(str(de))
        if not mn or not dn:
            unmapped.add((me, de))
            continue
        mm, mplace = mn.split("_")          # "08_corner"
        dd, dplace = dn.split("_")
        key = f"{mm}-{dd}"
        index.setdefault(key, []).append(
            {"id": a, "owner": owner[a], "mp": mplace[0], "dp": dplace[0]})
    if unmapped:
        print(f"NOTE {len(unmapped)} element values missing from element_map.json "
              f"(new values need a re-calibrate): {sorted(unmapped)[:6]}")

    # spot checks: refuse to publish an index that contradicts known pieces
    KNOWN = {23: "03-21", 24: "05-25"}      # MAR 21, MAY 25 — verified from chain SVG
    for aid, want in KNOWN.items():
        got = next((k for k, v in index.items() for e in v if e["id"] == aid), None)
        if got != want and aid in owner:
            raise SystemExit(f"sanity FAILED: asset {aid} indexed as {got}, expected {want}")

    # assetIds are a sequential mint counter (dense runs like 28476..28487 and
    # low ids 21..24 both exist), so lifetime mints ~= max live id and
    # burned = lifetime - alive. Sells burn newest-first, so the newest mint is
    # always in the live set and maxId is never understated.
    max_id = max(ids) if ids else 0
    out = {"generated": int(time.time()), "token": TOKEN,
           "items": sum(len(v) for v in index.values()),
           "burned": max(0, max_id - len(ids)),
           "days": index}
    os.makedirs(os.path.dirname(INDEX_PATH), exist_ok=True)
    json.dump(out, open(INDEX_PATH, "w"), separators=(",", ":"), sort_keys=True)
    print(f"wrote {INDEX_PATH}: {out['items']} items across {len(index)} days")


if __name__ == "__main__":
    {"calibrate": calibrate, "build": build}.get(
        sys.argv[1] if len(sys.argv) > 1 else "", lambda: sys.exit(__doc__))()
