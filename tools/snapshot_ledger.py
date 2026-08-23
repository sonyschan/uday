#!/usr/bin/env python3
"""Append an accruedCreatorQuote snapshot to data/gift-ledger.json.

The ledger is Phase 2's ground truth: income(day D) = accrued at D+1 00:00
UTC+8 minus accrued at D 00:00 (plus any withdrawals made in between —
withdraw right after a snapshot to keep the ledger monotone). Runs on every
hourly CI pass; a row is ~40 bytes, so a year is ~350KB of history.

A negative delta means an unrecorded withdrawal: flagged loudly, still
recorded — the ledger never lies about what the chain said.
"""
import json, os, ssl, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(ROOT, "data", "gift-ledger.json")
HOOK = "0xa726975b51E716708417374C39180C1f12E960cc"      # launchTaxHook
CREATOR = "e72d42810212c856636cd9d019e98cfe985535fd"      # fee recipient
SEL = "0xd206932b"                                        # accruedCreatorQuote(address,address)


def rpc_url():
    u = os.environ.get("ROBINHOOD_RPC_URL")
    if u:
        return u
    try:
        for line in open(os.path.join(ROOT, ".env")):
            if line.startswith("ROBINHOOD_RPC_URL="):
                return line.strip().split("=", 1)[1]
    except FileNotFoundError:
        pass
    return "https://rpc.mainnet.chain.robinhood.com/rpc"


def _ctx():
    for ca in ("/etc/ssl/cert.pem", "/private/etc/ssl/cert.pem"):
        if os.path.exists(ca):
            return ssl.create_default_context(cafile=ca)
    return ssl.create_default_context()


def main():
    data = SEL + CREATOR.zfill(64) + "0" * 64             # (creator, native ETH)
    payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_call",
               "params": [{"to": HOOK, "data": data}, "latest"]}
    req = urllib.request.Request(rpc_url(), json.dumps(payload).encode(),
                                 {"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=30, context=_ctx()))
    wei = int(r["result"], 16)

    try:
        rows = json.load(open(LEDGER))
    except FileNotFoundError:
        rows = []
    if rows and wei < rows[-1]["accruedWei"]:
        print(f"WARNING: accrued DECREASED {rows[-1]['accruedWei']} -> {wei} — "
              f"a withdrawal happened; note it before computing that day's income")
    rows.append({"ts": int(time.time()), "accruedWei": wei})
    json.dump(rows, open(LEDGER, "w"), separators=(",", ":"))
    print(f"ledger: {len(rows)} rows · accrued {wei / 1e18:.9f} ETH")


if __name__ == "__main__":
    main()
