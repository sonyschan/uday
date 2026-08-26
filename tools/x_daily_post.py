#!/usr/bin/env python3
"""Post the day's uDAY card to X.

Deliberately posts NO URL. X bills a post containing a link at $0.200 against
$0.015 without one (docs.x.com pay-per-use, 2026) and ranks link posts lower;
uday.gift is painted into the card and lives in the profile instead. That is
13x cheaper and reaches further — $5.48 a year at one post a day.

Runs from .github/workflows/post-x.yml after the gift root lands, so the
day's pot is already known. Without credentials it prints and exits 0, so the
workflow stays green until the secrets exist.

env: X_API_KEY X_API_SECRET X_ACCESS_TOKEN X_ACCESS_SECRET
usage: python3 tools/x_daily_post.py [MM-DD] [--dry-run]
"""
import json, os, sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from x_daily_card import build, today_key, ROOT
from x_daily_line import line_for

MEDIA_URL = "https://api.x.com/2/media/upload"
TWEET_URL = "https://api.x.com/2/tweets"
KEYS = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")


def gift_of(day):
    """The day's posted gift, with the counts the pot was actually built from.

    The list freezes at 00:00 UTC+8 while the index keeps moving, so quoting
    a live wallet count next to a frozen pot reads as broken arithmetic
    ("6 wallets ... 2 USDG"). When a root exists, its own numbers win."""
    y = datetime.now(timezone(timedelta(hours=8))).year
    path = os.path.join(ROOT, "data", "gift", "%d-%s.json" % (y, day))
    if not os.path.exists(path):
        return None
    g = json.load(open(path))
    return {"pot": g["total"] / 1e6, "pieces": g["totalPieces"],
            "wallets": len(g["claims"])}


def compose_text(meta, gift):
    n = gift or meta                       # frozen numbers when a pot exists
    plural = lambda k, w: "%d %s%s" % (n[k], w, "" if n[k] == 1 else "s")
    lines = ["%s is lit onchain." % meta["label"], ""]
    if gift:
        lines.append("%s carry this date, held by %s. Today %s USDG is waiting for them."
                     % (plural("pieces", "piece"), plural("wallets", "wallet"),
                        "%g" % gift["pot"]))
    else:
        lines.append("%s carry this date, held by %s."
                     % (plural("pieces", "piece"), plural("wallets", "wallet")))
    closer, src = line_for(meta["day"], verbose=True)
    lines += ["", closer]
    return "\n".join(lines), src


def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("-")]
    day = argv[0] if argv else today_key()
    dry = "--dry-run" in sys.argv and "--check" not in sys.argv

    card = os.path.join(ROOT, "data", "x-card.png")
    meta = build(day, card)
    text, src = compose_text(meta, gift_of(day))
    print("\n--- post text ---\n%s\n-----------------" % text)
    print("closing line source: %s" % (src or "(fallback — no factual claim)"))

    missing = [k for k in KEYS if not os.environ.get(k)]
    if dry or missing:
        print("not posting (%s)" % ("--dry-run" if dry else "no credentials: " + ",".join(missing)))
        return

    from requests_oauthlib import OAuth1Session
    x = OAuth1Session(os.environ["X_API_KEY"], os.environ["X_API_SECRET"],
                      os.environ["X_ACCESS_TOKEN"], os.environ["X_ACCESS_SECRET"])

    with open(card, "rb") as fh:
        # v2 upload rejects a bare file: media_category and media_type are required
        r = x.post(MEDIA_URL, files={"media": ("card.png", fh, "image/png")},
                   data={"media_category": "tweet_image", "media_type": "image/png"})
    if r.status_code >= 300:
        sys.exit("media upload failed %d: %s" % (r.status_code, r.text[:400]))
    media_id = str((r.json().get("data") or r.json())["id"])

    if "--check" in sys.argv:
        # Credentials and write scope proven without publishing: an uploaded
        # media id is private until a post references it, and upload is not
        # billed. Stops here on purpose.
        print("credentials OK, media accepted (id %s) — nothing posted" % media_id)
        return

    r = x.post(TWEET_URL, json={"text": text, "media": {"media_ids": [media_id]}})
    if r.status_code >= 300:
        sys.exit("post failed %d: %s" % (r.status_code, r.text[:400]))
    print("posted: https://x.com/udaygift/status/%s" % r.json()["data"]["id"])


if __name__ == "__main__":
    main()
