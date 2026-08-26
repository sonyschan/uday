#!/usr/bin/env python3
"""Build data/communities.json from UdayCommunity + the date index.

Everything is read, never scanned: this chain caps eth_getLogs at 10 blocks,
so the contract exposes allCommunities()/seenMembers() and this walks them
through Multicall3 — one RPC request per batch, because the public node rate
limits per request, not per sub-call.

Three things are verified off-chain, and each one drops a member quietly
rather than erroring:
  1. isMember — they may have left
  2. balanceOf >= minBalance — they may have sold below the gate
  3. they actually hold a piece of the day they declared — the chain cannot
     check this at all, because a uDAY's date lives only inside its art

usage: python3 tools/build_communities.py [--addr 0x...]
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_date_index import eth_call, eth_call_batch, u256, ROOT  # noqa: E402

OUT = os.path.join(ROOT, "data", "communities.json")
INDEX = os.path.join(ROOT, "data", "date-index.json")
ADDR_FILE = os.path.join(ROOT, "data", "community-contract.txt")

# computed with `cast sig`, not recalled — five of the six I first wrote from
# memory were wrong, which is the exact failure this project keeps repeating
SEL_ALL      = "0xd968226e"   # allCommunities()
SEL_COMM     = "0xbd6a7a82"   # communities(bytes32)
SEL_SEEN     = "0x217d5a01"   # seenMembers(bytes32)
SEL_ISMEMBER = "0x10ad56b3"   # isMember(bytes32,address)
SEL_DAYSOF   = "0xd98ceee6"   # daysOf(address)
SEL_BALANCE  = "0x70a08231"   # balanceOf(address)


def contract_addr():
    a = None
    for i, x in enumerate(sys.argv):
        if x == "--addr":
            a = sys.argv[i + 1]
    if not a and os.path.exists(ADDR_FILE):
        a = open(ADDR_FILE).read().strip()
    if not a:
        sys.exit("no community contract address (--addr, or data/community-contract.txt)")
    return a.lower()


def dec_addr(word):     return "0x" + word[-40:]
def dec_uint(word):     return int(word, 16)


def words(hexstr):
    b = hexstr[2:] if hexstr.startswith("0x") else hexstr
    return [b[i:i + 64] for i in range(0, len(b), 64)]


def dec_str(blob, off):
    """A dynamic string at byte offset `off` inside `blob` (hex, no 0x)."""
    n = int(blob[off * 2:off * 2 + 64], 16)
    raw = blob[off * 2 + 64: off * 2 + 64 + n * 2]
    return bytes.fromhex(raw).decode("utf-8", "replace")


def dec_array(hexstr):
    w = words(hexstr)
    if len(w) < 2:
        return []
    n = int(w[1], 16)
    return w[2:2 + n]


def main():
    C = contract_addr()
    idx = json.load(open(INDEX))
    days = idx["days"]

    ids = dec_array(eth_call(C, SEL_ALL))
    if not ids:
        json.dump({"contract": C, "communities": []}, open(OUT, "w"), indent=1)
        print("no communities yet")
        return

    metas = eth_call_batch([(C, SEL_COMM + i) for i in ids])
    out = []
    for cid, meta in zip(ids, metas):
        if not meta:
            continue
        blob = meta[2:]
        w = words(meta)
        token = dec_addr(w[0])
        comm = {
            "id": "0x" + cid,
            "token": token,
            "minBalance": str(dec_uint(w[1])),
            "creator": dec_addr(w[2]),
            "createdAt": dec_uint(w[3]),
            "slug": dec_str(blob, dec_uint(w[4])),
            "name": dec_str(blob, dec_uint(w[5])),
        }
        seen = [dec_addr(x) for x in dec_array(eth_call(C, SEL_SEEN + cid))]
        if seen:
            # one batch answers all three questions for every candidate
            checks = ([(C, SEL_ISMEMBER + cid + u256(int(a, 16))) for a in seen] +
                      [(token, SEL_BALANCE + u256(int(a, 16))) for a in seen] +
                      [(C, SEL_DAYSOF + u256(int(a, 16))) for a in seen])
            res = eth_call_batch(checks)
            n = len(seen)
            still, bals, dayss = res[:n], res[n:2 * n], res[2 * n:]
            floor = dec_uint(w[1])
            members = []
            for a, m, b, d in zip(seen, still, bals, dayss):
                if not m or dec_uint(m) != 1:
                    continue                                    # left
                if not b or dec_uint(b) < floor:
                    continue                                    # sold below the gate
                declared = [dec_uint(x) for x in dec_array(d or "0x")]
                held = []
                for mmdd in declared:
                    key = "%02d-%02d" % (mmdd // 100, mmdd % 100)
                    # the chain cannot check this; the index is the only place
                    # a uDAY's date is known at all
                    if any(e["owner"] == a for e in days.get(key, [])):
                        held.append(key)
                if held:
                    members.append({"addr": a, "days": held})
            comm["members"] = sorted(members, key=lambda m: m["addr"])
        else:
            comm["members"] = []
        out.append(comm)
        print("  %-16s %d member%s  gate %s @ %s" %
              (comm["slug"], len(comm["members"]), "" if len(comm["members"]) == 1 else "s",
               comm["minBalance"], comm["token"][:10]))

    json.dump({"contract": C, "communities": out}, open(OUT, "w"), indent=1, sort_keys=True)
    print("wrote %s (%d communities)" % (OUT, len(out)))


if __name__ == "__main__":
    main()
