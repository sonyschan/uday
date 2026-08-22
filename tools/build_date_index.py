# -*- coding: utf-8 -*-
"""uDAY date index builder — the only date search that can exist for uDAY.

uToken's own metadata cannot tell AUG 22 from JAN 01 (its trait names for the
month/date layers are just "Center"/"Corner"), so the date identity lives ONLY
in the art. This script reads each asset's art STRAIGHT FROM THE CHAIN and
decodes the glyphs, then publishes data/date-index.json for the site to serve
statically — visitors never touch the RPC.

Pipeline (assumption-free — the art IS the ground truth):
  token.layerReveal() -> the reveal sidecar (0x7317...34f1 at time of writing)
  sidecar.generateSvgForAsset(id) -> the EXACT svg uToken renders (verified
    byte-identical for #24), a pure <rect> grid
  raster 96x96 in-process -> pixel-match the date glyph (painted last, exact),
    then the month glyph (excluding the date's opaque region), against our own
    layer PNGs in assets/layers/** — byte-identical to what was uploaded.

Two dead ends this replaced, kept here so nobody walks them again:
  - element-order formulas ("descending, corner-first") fit month but not date;
  - generateAppearanceSeed(id) on the launch-tx helper 0x9815...27d8 is a
    PREVIEW SAMPLER, not the asset's stored appearance — calibrating art
    against it scattered 11 different labels over one element value. The
    built-in sanity anchors (#23=MAR21, #24=MAY25, verified against uToken's
    own client render) are what caught both.

Usage:  python3 tools/build_date_index.py build

Decoded art is cached in data/art-cache.json (committed): an asset's art is
immutable once its reveal settles (owner-confirmed), so each id is decoded
once; the youngest ids are re-decoded every run to absorb pending reveals.
Stdlib + PIL. Selectors hardcoded (no keccak in stdlib):
  layerReveal()                 0xb509d6c4
  generateSvgForAsset(uint256)  0xeb3fbd83
"""
import json, os, re, ssl, sys, time, urllib.request

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
    if isinstance(req, str):
        req = urllib.request.Request(req, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout, context=_CTX)

ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _rpcs():
    """ROBINHOOD_RPC_URL (env, or a local .env line) first — a dedicated
    endpoint (Alchemy) does ~0.65s/svg with 10 workers where the public node
    serializes to ~4s — then the public node as fallback."""
    urls = []
    env = os.environ.get("ROBINHOOD_RPC_URL")
    if not env:
        try:
            for line in open(os.path.join(ROOT, ".env")):
                if line.startswith("ROBINHOOD_RPC_URL="):
                    env = line.split("=", 1)[1].strip()
        except FileNotFoundError:
            pass
    if env:
        urls.append(env)
    urls += ["https://rpc.mainnet.chain.robinhood.com",
             "https://rpc.mainnet.chain.robinhood.com/rpc"]
    return urls

RPCS = _rpcs()
TOKEN    = "0x359211bb6b8cabce02dcbec1c55b50f2ec884146"
MULTICALL = "0xcA11bde05977b3631167028862bE2a173976CA11"
SEL_AGG3  = "82ad56cb"
SEL_SIDECAR = "0xb509d6c4"      # layerReveal()
SEL_SVG_ASSET = "0xeb3fbd83"    # generateSvgForAsset(uint256)
API       = f"https://utoken.so/api/tokens/{TOKEN}"
CACHE_PATH = os.path.join(ROOT, "data", "art-cache.json")
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
    """calls: [(to, data)] -> [result_hex|None], packed through ONE Multicall3
    aggregate3 eth_call — the public node rate-limits per REQUEST, so N reads
    must cost one request, not N. (JSON-RPC batching counted per sub-call and
    ground the sweep to ~19 ids/min.)"""
    n = len(calls)
    # ── encode aggregate3: dynamic array of (address,bool,bytes) tuples ──
    tuples = []
    for to, data in calls:
        cd = bytes.fromhex(data[2:])
        t = (u256(int(to, 16))                     # address
             + u256(1)                             # allowFailure = true
             + u256(0x60)                          # offset of bytes within tuple
             + u256(len(cd))
             + cd.hex().ljust(((len(cd) + 31) // 32) * 64, "0"))
        tuples.append(t)
    offs, pos = [], 32 * n
    for t in tuples:
        offs.append(u256(pos)); pos += len(t) // 2
    payload = SEL_AGG3 + u256(0x20) + u256(n) + "".join(offs) + "".join(tuples)
    raw = eth_call(MULTICALL, "0x" + payload)
    blob = bytes.fromhex(raw[2:])
    # ── decode (bool success, bytes returnData)[] ──
    arr = int.from_bytes(blob[0:32], "big")            # offset of array
    cnt = int.from_bytes(blob[arr:arr + 32], "big")
    base = arr + 32
    res = []
    for i in range(cnt):
        toff = int.from_bytes(blob[base + 32 * i: base + 32 * i + 32], "big")
        tp = base + toff
        ok = int.from_bytes(blob[tp:tp + 32], "big")
        doff = int.from_bytes(blob[tp + 32:tp + 64], "big")
        dp = tp + doff
        dlen = int.from_bytes(blob[dp:dp + 32], "big")
        data = blob[dp + 32:dp + 32 + dlen]
        res.append("0x" + data.hex() if ok and dlen else None)
    return res


def u256(n):
    return format(n, "064x")


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


_OPAQUE = {}          # id(candidates dict) -> {name: [(x, y, rgb), ...]}


def _opaque_list(candidates):
    key = id(candidates)
    if key not in _OPAQUE:
        table = {}
        for name, im in candidates.items():
            cp = im.load()
            table[name] = [(x, y, cp[x, y][:3])
                           for y in range(96) for x in range(96)
                           if cp[x, y][3] >= 250]
        _OPAQUE[key] = table
    return _OPAQUE[key]


def match_glyph(composite, candidates, exclude=None):
    """Which candidate PNG's opaque pixels appear verbatim in the composite?
    `exclude`: opaque coordinate set painted AFTER this layer (the date layer
    overdraws the month layer), skipped during comparison. Iterates only each
    candidate's precomputed opaque pixels — the naive 96x96xN scan was the
    sweep's bottleneck once the RPC went parallel."""
    px = composite.load()
    best = None
    for name, pixels in _opaque_list(candidates).items():
        ok = checked = 0
        for x, y, rgb in pixels:
            if exclude and (x, y) in exclude:
                continue
            checked += 1
            if px[x, y] == rgb:
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
    # Assets still inside their reveal window carry PROVISIONAL values (owner-
    # confirmed: traits fix only once reveal completes). Re-read the youngest
    # ids every run so a value cached mid-reveal heals itself.
    young = set(a for a in ids if a > max(ids) - 1500) if ids else set()
    unrevealed = sorted(a for a in ids
                        if isinstance(cache.get(a), dict) and cache[a].get("u")
                        and a not in young)
    slot = int(time.time() // 3600) % 24
    recheck = set(unrevealed[slot::24])      # ~1/24 of them per hourly run
    todo = [a for a in ids if a not in cache or a in young or a in recheck]
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
    CH = 250         # ids per chunk = 500 sub-calls in ONE aggregate3 request
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
        if True:
            print(f"  ids {min(i+CH,len(todo))}/{len(todo)}")
    return cache



def u256(n):
    return format(n, "064x")


def sidecar():
    return "0x" + eth_call(TOKEN, SEL_SIDECAR)[-40:]


def load_cache():
    try:
        return {int(k): v for k, v in json.load(open(CACHE_PATH)).items()}
    except FileNotFoundError:
        return {}


def flush_cache(cache):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    tmp = CACHE_PATH + ".tmp"
    json.dump({str(k): v for k, v in sorted(cache.items())}, open(tmp, "w"),
              separators=(",", ":"))
    os.replace(tmp, CACHE_PATH)


def decode_svg(raw, months, dates, frames, plates):
    """ABI-encoded string result -> full recipe dict, or None (unrevealed).
    Match order is reverse paint order — each layer's pixels are exact except
    where a LATER layer overdrew them: date (last, exact) -> month -> frame ->
    plate. plate/frame may be absent (80%/20% presence): no match = absent.
    The full recipe is captured now because the holder-HD feature needs it —
    re-sweeping 6k heavy renders later to recover two skipped fields would
    cost hours."""
    b = bytes.fromhex(raw[2:])
    ln = int.from_bytes(b[32:64], "big")
    svg = b[64:64 + ln].decode()
    comp = raster(svg)
    d = match_glyph(comp, dates)                       # date paints last: exact
    if d is None:
        return None
    excl = set((x, y) for x, y, _ in _opaque_list(dates)[d])
    mo = match_glyph(comp, months, exclude=excl)
    if mo is None:
        return None
    excl |= set((x, y) for x, y, _ in _opaque_list(months)[mo])
    fr = match_glyph(comp, frames, exclude=excl)
    if fr:
        excl |= set((x, y) for x, y, _ in _opaque_list(frames)[fr])
    pl = match_glyph(comp, plates, exclude=excl)
    mm, mp = mo.split("_"); dd, dp = d.split("_")
    P = {"corner": "r", "center": "c"}       # both words start with "c" — [0] was ambiguous
    return {"d": mm + "-" + dd, "mp": P[mp], "dp": P[dp],
            "f": fr or "", "p": pl or ""}


def build():
    months = layer_pngs("month"); dates = layer_pngs("date")
    frames = layer_pngs("frame"); plates = layer_pngs("plate")
    sc = sidecar()
    print("sidecar", sc)
    assets = fetch_assets()
    ids = [a for a, _ in assets]
    owner = dict(assets)
    print(f"{len(ids)} live assets")

    cache = load_cache()
    # Art is immutable once the reveal settles; only pending reveals can still
    # move, so the youngest ids are re-decoded every run.
    young = set(a for a in ids if a > max(ids) - 1500) if ids else set()
    unrevealed = sorted(a for a in ids
                        if isinstance(cache.get(a), dict) and cache[a].get("u")
                        and a not in young)
    slot = int(time.time() // 3600) % 24
    recheck = set(unrevealed[slot::24])      # ~1/24 of them per hourly run
    todo = [a for a in ids if a not in cache or a in young or a in recheck]
    import concurrent.futures as cf

    def fetch_one(a):
        """SVG generation is compute-heavy on the node (~seconds each); the
        win is CONCURRENCY, not batching — a multicall of generations blows
        the eth_call gas cap anyway.

        A failure and an empty result must never share a shape (the repo's
        oldest lesson): only an EXECUTION REVERT means "nothing to render".
        Capacity/throughput errors (Alchemy -32005 etc. arrive as JSON-RPC
        errors, not HTTP 429) are retried here — the first sweep silently
        recorded 5k rate-limited assets as unrevealed."""
        for attempt in range(6):
            try:
                return a, eth_call(sc, SEL_SVG_ASSET + u256(a))
            except RuntimeError as e:
                msg = str(e)
                if "revert" in msg:
                    return a, "REVERT"
                time.sleep(8 * (attempt + 1))     # capacity error: back off, retry
        return a, None                            # transport dead: leave for next run

    LANES, CH = 8, 100
    with cf.ThreadPoolExecutor(LANES) as ex:
        for i in range(0, len(todo), CH):
            part = todo[i:i + CH]
            for a, raw in ex.map(fetch_one, part):
                if raw is None:
                    continue                       # transient failure: retry next run
                if raw == "REVERT":
                    cache[a] = {"u": 1}            # renderer reverts: nothing to render
                    continue
                v = decode_svg(raw, months, dates, frames, plates)
                # v None = svg exists but carries no date glyph (mid-reveal):
                # also marked unrevealed; re-checked on the rotating slice below
                cache[a] = v if v is not None else {"u": 1}
            flush_cache(cache)                # checkpoint per chunk
            print(f"  decoded {min(i+CH,len(todo))}/{len(todo)}")

    index = {}
    for a in ids:
        v = cache.get(a)
        if not v or v.get("u"):
            continue
        index.setdefault(v["d"], []).append(
            {"id": a, "owner": owner[a], "mp": v["mp"], "dp": v["dp"],
             "p": v["p"], "f": v["f"]})

    # sanity anchors — verified against uToken's own client render; refuse to
    # publish an index that contradicts them
    KNOWN = {23: "03-21", 24: "05-25"}
    for aid, want in KNOWN.items():
        if aid in owner:
            got = (cache.get(aid) or {}).get("d")
            if got != want:
                raise SystemExit(f"sanity FAILED: asset {aid} decoded as {got}, expected {want}")

    max_id = max(ids) if ids else 0
    dated = sum(len(v) for v in index.values())
    out = {"generated": int(time.time()), "token": TOKEN,
           "items": dated,
           "alive": len(ids),
           "unrevealed": sum(1 for a in ids
                             if isinstance(cache.get(a), dict) and cache[a].get("u")),
           "burned": max(0, max_id - len(ids)),
           # unique owners across ALL alive items, sealed included — matches
           # uToken's "item owners" stat; owners-of-dated-only is a subset
           # and reads as a wrong number next to the collection page
           "owners": len(set(owner.values())),
           "days": index}
    os.makedirs(os.path.dirname(INDEX_PATH), exist_ok=True)
    json.dump(out, open(INDEX_PATH, "w"), separators=(",", ":"), sort_keys=True)
    print(f"wrote {INDEX_PATH}: {out['items']} items across {len(index)} days")


if __name__ == "__main__":
    if (sys.argv[1:] or [""])[0] != "build":
        sys.exit(__doc__)
    build()
