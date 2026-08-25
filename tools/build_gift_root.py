#!/usr/bin/env python3
"""Build the daily Claim Gift merkle root.

Phase 1 formula: $1 USDG (6 decimals) per PIECE of today's date — per-piece is
sybil-neutral (splitting pieces across wallets changes nothing) and Phase 2
becomes a formula swap in THIS file only; the contract never changes.

usage:  python3 tools/build_gift_root.py [MM-DD] [--year YYYY]
        (default: today in UTC+8, the gift day's fixed timezone)

Reads  data/date-index.json  (the same index uday.gift serves).
Writes data/gift/YYYY-MM-DD.json  — root + per-address proofs. The file is
committed and served statically; public proofs are safe because the contract
pays the leaf address, never the submitter.

keccak256 comes from foundry's `cast` — available locally, and installed in CI
by .github/workflows/post-gift.yml (foundry-toolchain), which runs this daily
via tools/ci-post-gift.sh. The amount formula here is public by choice: every
published data/gift/*.json already carries unit and per-address amounts.
"""
import json, os, subprocess, sys
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "data", "date-index.json")
OUTDIR = os.path.join(ROOT, "data", "gift")
UNIT = 1_000_000                     # $1 USDG per piece  <-- the Phase 2 swap point


def keccak(hexdata: str) -> str:
    out = subprocess.run(["cast", "keccak", "0x" + hexdata],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()[2:].lower()


def leaf_hash(addr: str, amount: int) -> str:
    # abi.encodePacked(address, uint256)
    return keccak(addr[2:].lower().zfill(40) + format(amount, "064x"))


def merkle(leaves):
    """Sorted-pair tree, odd node promoted — matches UdayGift.claim()."""
    layers = [leaves[:]]
    while len(layers[-1]) > 1:
        cur, nxt = layers[-1], []
        for i in range(0, len(cur) - 1, 2):
            a, b = sorted((cur[i], cur[i + 1]))
            nxt.append(keccak(a + b))
        if len(cur) % 2:
            nxt.append(cur[-1])
        layers.append(nxt)
    proofs = []
    for idx in range(len(leaves)):
        path, i = [], idx
        for layer in layers[:-1]:
            sib = i ^ 1
            if sib < len(layer):
                path.append("0x" + layer[sib])
            i //= 2
        proofs.append(path)
    return "0x" + layers[-1][0], proofs


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    now = datetime.now(timezone(timedelta(hours=8)))
    key = args[0] if args else now.strftime("%m-%d")
    year = now.year
    for i, a in enumerate(sys.argv):
        if a == "--year":
            year = int(sys.argv[i + 1])
    day_id = int(f"{year}{key[:2]}{key[3:]}")

    days = json.load(open(INDEX))["days"]
    pieces = days.get(key, [])
    if not pieces:
        sys.exit(f"{key}: no dated pieces — nothing to post; the pot rolls per the ledger")

    counts = {}
    for e in pieces:
        counts[e["owner"]] = counts.get(e["owner"], 0) + 1
    entries = sorted(counts.items())                     # deterministic order
    leaves = [leaf_hash(a, n * UNIT) for a, n in entries]
    root, proofs = merkle(leaves)

    out = {
        "day": key, "dayId": day_id, "root": root,
        "unit": UNIT, "totalPieces": len(pieces),
        "total": sum(n for _, n in entries) * UNIT,
        "claims": {a: {"amount": n * UNIT, "count": n, "proof": proofs[i]}
                   for i, (a, n) in enumerate(entries)},
    }
    os.makedirs(OUTDIR, exist_ok=True)
    path = os.path.join(OUTDIR, f"{year}-{key}.json")
    json.dump(out, open(path, "w"), indent=1, sort_keys=True)

    print(f"wrote {path}")
    print(f"  {len(entries)} wallets · {len(pieces)} pieces · total {out['total']/1e6:.2f} USDG")
    print(f"  post it:  cast send $GIFT 'setRoot(uint32,bytes32)' {day_id} {root} \\")
    print(f"            --rpc-url $ROBINHOOD_RPC_URL --account <owner-or-poster>")


if __name__ == "__main__":
    main()
