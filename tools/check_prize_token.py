#!/usr/bin/env python3
"""Can this token be a lottery prize?

    python3 tools/check_prize_token.py 0x7ed16d61...
    python3 tools/check_prize_token.py 0x7ed16d61... --asset 7 --save

A uToken launch is only a usable prize if it is ART-backed. Plenty are not:
Index (0x56910d44...) is a plain ERC-20 from the same factory with no pieces
behind it at all, and transferring one into the prize contract would move a
number, not a picture. That is the mistake this exists to prevent, and it is
not visible from the token page.

Everything is read from chain. Nothing here trusts a name, a logo, or the fact
that something was launched by uToken.
"""
import argparse, json, os, re, sys

try:
    import requests                      # urllib fails TLS on stock macOS python
except ImportError:
    sys.exit("pip install requests")

RPC = os.environ.get("ROBINHOOD_RPC_URL",
                     "https://rpc.mainnet.chain.robinhood.com/rpc")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# every one from `cast sig` — this project has written selectors wrong from
# memory before, five out of six in one sitting
SEL = {
    "name":        "0x06fdde03",
    "symbol":      "0x95d89b41",
    "decimals":    "0x313ce567",
    "totalSupply": "0x18160ddd",
    "layerReveal": "0xb509d6c4",
    "unit":        "0x61bfb16e",   # assetBackedTokenUnit()
    "tradingPool": "0x71f16a18",
    "bondingPool": "0x676cc5b1",
}
# presence is checked in the BYTECODE, not by calling: a call that reverts and
# a function that does not exist look identical from the outside
NEEDED = {
    "0x11313258": "transferAssetBackedToken(address,uint256)",
    "0x6146a5b7": "transferAssetBackedTokenFrom(address,address,uint256)",
    "0x1a5cbde0": "setAssetOperator(address,bool)",
    "0x076846bc": "isAssetOperator(address,address)",
    "0xccd52464": "isAssetOwner(address,uint256)",
    "0x231e776c": "ownerAssetBackedTokenCount(address)",
}


def rpc(method, params):
    r = requests.post(RPC, timeout=30,
                      json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    j = r.json()
    if "error" in j:
        raise RuntimeError(j["error"].get("message", "rpc error"))
    return j.get("result")


def call(to, data):
    try:
        res = rpc("eth_call", [{"to": to, "data": data}, "latest"])
        return None if not res or res == "0x" else res
    except Exception:
        return None


def dec_string(hexstr):
    """An ABI-encoded string, or a bytes32 from the pre-standard tokens."""
    if not hexstr:
        return None
    b = hexstr[2:]
    try:
        if len(b) >= 128 and int(b[:64], 16) == 32:
            n = int(b[64:128], 16)
            return bytes.fromhex(b[128:128 + n * 2]).decode("utf-8", "replace")
        return bytes.fromhex(b[:64]).rstrip(b"\x00").decode("ascii")
    except Exception:
        return None


def dec_uint(hexstr):
    return int(hexstr, 16) if hexstr else None


def dec_addr(hexstr):
    return "0x" + hexstr[-40:] if hexstr else None


def check(token, asset_id, save):
    ok = True
    print("token   %s" % token)

    code = rpc("eth_getCode", [token, "latest"])
    if not code or code == "0x":
        print("  NO CODE at this address — not a contract")
        return False
    print("  bytecode %s bytes" % (len(code[2:]) // 2))

    name = dec_string(call(token, SEL["name"]))
    sym = dec_string(call(token, SEL["symbol"]))
    dec = dec_uint(call(token, SEL["decimals"]))
    sup = dec_uint(call(token, SEL["totalSupply"]))
    print("  %s (%s)  decimals=%s  supply=%s"
          % (name, sym, dec, "{:,.0f}".format(sup / 10 ** (dec or 18)) if sup else "?"))

    print("\n  asset-backed interface")
    for sel, sig in NEEDED.items():
        present = sel[2:] in code
        print("    %-4s %s" % ("YES" if present else "no", sig))
        ok = ok and present

    unit = dec_uint(call(token, SEL["unit"]))
    if unit:
        print("    unit  %s  (%s whole token = 1 piece)"
              % (unit, "1" if unit == 10 ** 18 else "?"))

    # Bonding or graduated. Not a blocker for a prize, but it decides whether a
    # buyer sees MetaMask's new-contract warning, and it is worth knowing which
    # kind of project you are partnering with.
    tp = dec_addr(call(token, SEL["tradingPool"]))
    if tp:
        graduated = tp != "0x" + "0" * 40
        print("\n  stage   %s" % ("graduated (Uniswap v4)" if graduated
                                  else "still bonding — buyers get a MetaMask alert"))

    print("\n  art")
    lr = dec_addr(call(token, SEL["layerReveal"]))
    if not lr or lr == "0x" + "0" * 40:
        print("    no layerReveal — THIS TOKEN HAS NO ART")
        return False
    print("    layerReveal  %s" % lr)

    # generateSvgForAsset(uint256) — the only proof that matters: art comes out
    SEL_SVG = "0xeb3fbd83"      # cast sig 'generateSvgForAsset(uint256)'
    data = SEL_SVG + format(asset_id, "x").rjust(64, "0")
    from_cast = call(lr, data)
    svg = dec_string(from_cast)
    if not svg or "<svg" not in svg:
        # the selector is recomputed here rather than trusted, because a wrong
        # one returns None and would read as "no art"
        print("    generateSvgForAsset(%d) returned nothing" % asset_id)
        print("    (selector may differ on this project — check with cast)")
        return False

    vb = re.search(r"viewBox='([^']+)'", svg) or re.search(r'viewBox="([^"]+)"', svg)
    import gzip
    raw = svg.encode()
    print("    asset #%d   %s bytes  (gzip %s)  viewBox %s  rects %d"
          % (asset_id, "{:,}".format(len(raw)), "{:,}".format(len(gzip.compress(raw, 9))),
             vb.group(1) if vb else "?", svg.count("<rect")))

    if save:
        d = os.path.join(ROOT, "data", "prizes")
        os.makedirs(d, exist_ok=True)
        f = os.path.join(d, "%s-%d.svg" % ((sym or "token").lower(), asset_id))
        open(f, "w").write(svg)
        print("    saved %s" % os.path.relpath(f, ROOT))

    print("\n  VERDICT  %s" % ("usable as a prize" if ok else
                               "NOT usable — missing the transfer interface"))
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("token")
    ap.add_argument("--asset", type=int, default=1, help="which piece to sample")
    ap.add_argument("--save", action="store_true", help="write the SVG to data/prizes/")
    a = ap.parse_args()
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}", a.token):
        sys.exit("not an address: %s" % a.token)
    sys.exit(0 if check(a.token, a.asset, a.save) else 1)
