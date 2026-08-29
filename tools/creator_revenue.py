#!/usr/bin/env python3
"""What the creator fee actually earned, per day.

    python3 tools/creator_revenue.py              # print the report
    python3 tools/creator_revenue.py --days 14    # a longer window
    python3 tools/creator_revenue.py --telegram   # and send it

uDAY is ETH-quoted, so the 0.7% creator share ACCRUES on the launch hook
instead of landing in the wallet on every swap (an ERC-20-quoted launch pushes
it; this one does not). That means there is no wallet balance to watch, and the
only per-day view is the trades themselves.

Two numbers, derived two ways, and the report prints both on purpose:

  * per-day revenue, from uToken's trade list x 0.7%
  * total unclaimed, read straight off the hook

They measure different spans — the hook is cumulative since the last withdrawal
— but if the daily figures are sane the accrued total should never be smaller
than the days that have not been claimed. It is the only cross-check available.

THE PAGINATION IS NOT WHAT IT LOOKS LIKE. `limit` is accepted and ignored:
limit=10 and limit=1000 both return 50. The working parameter is `page`, and
a paged request returns 40 per page while no parameter at all returns 50. So
the walk below is by page, deduplicated by trade id, and stops on the first
page that carries nothing new — never trust a count here, only ids.
"""
import argparse, json, os, sys, time
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import requests                      # urllib fails TLS on stock macOS python
except ImportError:
    sys.exit("pip install requests")

TOKEN   = "0x359211bb6b8cabce02dcbec1c55b50f2ec884146"
API     = "https://utoken.so/api/tokens/" + TOKEN
HOOK    = "0xa726975b51E716708417374C39180C1f12E960cc"
CREATOR = "0xe72d42810212c856636cd9d019e98cfe985535fd"
RPC     = os.environ.get("ROBINHOOD_RPC_URL",
                         "https://rpc.mainnet.chain.robinhood.com/rpc")
TZ8     = dt.timezone(dt.timedelta(hours=8))    # the owner's day, and the gift's
CREATOR_SHARE = 0.007                           # 70% of a 1% swap tax
ROOT    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def trades(max_pages=40):
    """Every trade the API will give us, deduplicated by id."""
    out, page = {}, 0
    while page < max_pages:
        page += 1
        url = API + "/trades" + ("" if page == 1 else "?page=%d" % page)
        try:
            r = requests.get(url, timeout=30)
            batch = r.json().get("trades", [])
        except Exception as e:
            print("  ! page %d failed (%s) — report covers what came back" % (page, e),
                  file=sys.stderr)
            break
        fresh = [t for t in batch if t["id"] not in out]
        if not fresh:
            break                        # a page with nothing new is the end
        for t in fresh:
            out[t["id"]] = t
        # page 1 has to be asked for twice: bare returns 50, ?page=1 returns 40,
        # and the ten it leaves out are real trades
        if page == 1:
            try:
                for t in requests.get(url + "?page=1", timeout=30).json().get("trades", []):
                    out.setdefault(t["id"], t)
            except Exception:
                pass
    return list(out.values())


def accrued_eth():
    """Unclaimed creator fees sitting on the hook. None if the RPC will not answer."""
    # cast sig 'accruedCreatorQuote(address,address)' — computed, never recalled:
    # this project has written five of six selectors wrong from memory before.
    SEL = "0xd206932b"
    args = CREATOR[2:].lower().rjust(64, "0") + "0" * 64      # (creator, ETH = 0x0)
    try:
        r = requests.post(RPC, timeout=20, json={
            "jsonrpc": "2.0", "id": 1, "method": "eth_call",
            "params": [{"to": HOOK, "data": SEL + args}, "latest"]})
        res = r.json().get("result")
        return int(res, 16) / 1e18 if res and res != "0x" else None
    except Exception:
        return None


def eth_usd():
    try:
        d = requests.get(API, timeout=20).json()
        pq, pu = d.get("priceQuote"), d.get("priceUsd")
        return pu / pq if pq and pu else None
    except Exception:
        return None


def gift_spend():
    """What the gift actually paid out, per day, from the committed proof files."""
    out = {}
    d = os.path.join(ROOT, "data", "gift")
    if not os.path.isdir(d):
        return out
    for f in os.listdir(d):
        if not f.endswith(".json"):
            continue
        try:
            j = json.load(open(os.path.join(d, f)))
            out[j["day"]] = j["total"] / 1e6
        except Exception:
            pass
    return out


def report(days):
    tr = trades()
    by = {}
    for t in tr:
        k = dt.datetime.fromtimestamp(t["tsMs"] / 1000, TZ8).strftime("%m-%d")
        by.setdefault(k, []).append(t)

    today = dt.datetime.now(TZ8).strftime("%m-%d")
    keys = sorted(by)[-days:]
    spend = gift_spend()

    lines = []
    lines.append("uDAY creator revenue")
    lines.append("")
    head = "%-7s %5s %11s %9s %9s" % ("day", "n", "volume", "yours", "gift out")
    lines.append(head)
    lines.append("-" * len(head))
    for k in keys:
        vol = sum(x["valueUsd"] for x in by[k])
        rev = vol * CREATOR_SHARE
        out = spend.get(k)
        mark = "  <- today, still counting" if k == today else ""
        lines.append("%-7s %5d %11s %9s %9s%s" % (
            k, len(by[k]), "${:,.0f}".format(vol),
            "${:,.2f}".format(rev), "${:,.2f}".format(out) if out is not None else "-", mark))

    done = [k for k in keys if k != today]
    if done:
        y = done[-1]
        vol = sum(x["valueUsd"] for x in by[y])
        lines.append("")
        lines.append("yesterday ({}): ${:,.2f} on ${:,.0f} of volume".format(
            y, vol * CREATOR_SHARE, vol))
        wk = sum(sum(x["valueUsd"] for x in by[k]) for k in done)
        lines.append("last {} full days: ${:,.2f}".format(len(done), wk * CREATOR_SHARE))

    # The float, one line. gift_float.py is what ALERTS on it, but an alerter
    # that only speaks when something is wrong cannot be told apart from one
    # that has stopped running — so the number rides along with the digest that
    # arrives every day regardless. A chain hiccup must not take the digest
    # down with it, hence the catch.
    try:
        from gift_float import state as float_state
        f = float_state()
        lines.append("")
        lines.append("gift float: ${:,.2f} balance, ${:,.2f} free, {:.1f} days".format(
            f["balance"], f["free"], f["runway"]))
    except Exception as e:
        lines.append("")
        lines.append("gift float: unavailable ({})".format(str(e)[:60]))

    acc = accrued_eth()
    if acc is not None:
        px = eth_usd()
        lines.append("unclaimed on the hook: {:.6f} ETH{}".format(
            acc, " (~${:,.2f})".format(acc * px) if px else ""))
        lines.append("  withdrawCreatorQuoteAll() to collect — ETH-quoted fees never")
        lines.append("  arrive on their own.")
    return "\n".join(lines)


def telegram(text):
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        print("(TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — printed only)")
        return False
    r = requests.post("https://api.telegram.org/bot%s/sendMessage" % tok, timeout=25,
                      json={"chat_id": chat, "text": "```\n%s\n```" % text,
                            "parse_mode": "MarkdownV2",
                            "disable_web_page_preview": True})
    if not r.ok or not r.json().get("ok"):
        # a report that fails to send must fail loudly; a silent daily digest
        # that stopped arriving is indistinguishable from a quiet day
        sys.exit("telegram send failed %d: %s" % (r.status_code, r.text[:300]))
    print("sent to telegram")
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--telegram", action="store_true")
    a = ap.parse_args()
    txt = report(a.days)
    print(txt)
    if a.telegram:
        telegram(txt)
