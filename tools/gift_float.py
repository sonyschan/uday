#!/usr/bin/env python3
"""Is there enough USDG left to pay the gift?

    python3 tools/gift_float.py                     # print the figures
    python3 tools/gift_float.py --alert-below 15    # ...and shout if it is low

The contract's balance is not the money available. A day's root stays claimable
for claimWindow (72h at the time of writing, read live because changing it is
RETROACTIVE), so some of that balance is already promised to holders who simply
have not collected yet. Spend against the FREE float, never the balance.

Reads everything from chain rather than from the committed proof files, except
the per-day totals and recipient lists, which is what those files are for. A
day is open, and its unclaimed remainder is a liability, only if roots(dayId)
says it was posted inside the window.
"""
import argparse, json, os, sys
import datetime as dt

try:
    import requests                      # urllib fails TLS on stock macOS python
except ImportError:
    sys.exit("pip install requests")

GIFT = "0xBd17Ad7CD5586E8e42a73111c63A1B09985B1f09"
USDG = "0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168"      # Global Dollar, 6 dec
RPC  = os.environ.get("ROBINHOOD_RPC_URL",
                      "https://rpc.mainnet.chain.robinhood.com/rpc")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# every one from `cast sig`, never from memory
SEL_BALANCE = "0x70a08231"      # balanceOf(address)
SEL_WINDOW  = "0xc5d37ae1"      # claimWindow()
SEL_ROOTS   = "0x081dc681"      # roots(uint32) -> (bytes32 root, uint64 postedAt)
SEL_CLAIMED = "0x96638b6c"      # claimed(uint32,address)


def call(to, data):
    r = requests.post(RPC, timeout=25, json={
        "jsonrpc": "2.0", "id": 1, "method": "eth_call",
        "params": [{"to": to, "data": data}, "latest"]})
    res = r.json().get("result")
    return None if not res or res == "0x" else res


def word(hexstr, i):
    return hexstr[2:][i * 64:(i + 1) * 64]


def gift_days():
    d = os.path.join(ROOT, "data", "gift")
    out = []
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if f.endswith(".json"):
            try:
                out.append(json.load(open(os.path.join(d, f))))
            except Exception:
                pass
    return out


def state():
    bal = call(USDG, SEL_BALANCE + GIFT[2:].lower().rjust(64, "0"))
    if bal is None:
        # No balance means no answer, not zero. Saying "0 USDG left" because an
        # RPC blinked would send a false alarm at 09:00 every time the node
        # hiccups, and this project's notes are explicit that it does.
        raise RuntimeError("could not read the contract balance")
    balance = int(bal, 16) / 1e6

    win = call(GIFT, SEL_WINDOW)
    window = int(win, 16) if win else 259200

    now = dt.datetime.now(dt.UTC).timestamp()
    days, committed = [], 0.0
    for g in gift_days():
        r = call(GIFT, SEL_ROOTS + format(g["dayId"], "x").rjust(64, "0"))
        posted = int(word(r, 1), 16) if r else 0
        if not posted or now - posted >= window:
            continue                                   # never posted, or closed
        got = 0.0
        for addr, c in g["claims"].items():
            res = call(GIFT, SEL_CLAIMED + format(g["dayId"], "x").rjust(64, "0")
                             + addr[2:].lower().rjust(64, "0"))
            if res and int(res, 16) == 1:
                got += c["amount"] / 1e6
        total = g["total"] / 1e6
        days.append((g["day"], total, got, total - got, (now - posted) / 3600))
        committed += total - got

    recent = [g["total"] / 1e6 for g in gift_days()[-5:]]
    burn = sum(recent) / len(recent) if recent else 0.0
    free = balance - committed
    return dict(balance=balance, committed=committed, free=free,
                window_h=window / 3600, days=days, burn=burn,
                runway=(free / burn) if burn else float("inf"))


def render(s):
    L = ["uDAY gift float", "",
         "balance                 %8.2f USDG" % s["balance"],
         "promised, still open    %8.2f USDG" % s["committed"],
         "free to spend           %8.2f USDG" % s["free"], ""]
    if s["days"]:
        L.append("open days (%dh window)" % round(s["window_h"]))
        for day, tot, got, un, age in s["days"]:
            L.append("  %s  %5.2f total  %5.2f claimed  %5.2f open   %.0fh in"
                     % (day, tot, got, un, age))
        L.append("")
    L.append("recent payout   %.2f USDG/day" % s["burn"])
    L.append("runway          %.1f days if everyone claims" % s["runway"])
    return "\n".join(L)


def telegram(text):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        print("(TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — printed only)")
        return
    r = requests.post("https://api.telegram.org/bot%s/sendMessage" % tok, timeout=25,
                      json={"chat_id": chat, "text": "```\n%s\n```" % text,
                            "parse_mode": "MarkdownV2", "disable_web_page_preview": True})
    if not r.ok or not r.json().get("ok"):
        sys.exit("telegram send failed %d: %s" % (r.status_code, r.text[:300]))
    print("sent to telegram")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--alert-below", type=float, default=None,
                    help="send to Telegram when the BALANCE falls under this")
    ap.add_argument("--always", action="store_true", help="send whatever the balance")
    a = ap.parse_args()

    s = state()                     # a read failure exits non-zero, loudly
    txt = render(s)
    print(txt)

    low = a.alert_below is not None and s["balance"] < a.alert_below
    if a.always or low:
        head = ("LOW — under %.0f USDG. Top up %s\n\n" % (a.alert_below, GIFT)) if low else ""
        telegram(head + txt)
    elif a.alert_below is not None:
        print("above %.0f — nothing sent" % a.alert_below)
