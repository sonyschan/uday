#!/usr/bin/env python3
"""The day's closing line, written by Grok and grounded in a source.

Why events and not quotes: a quote about time is interchangeable — Marcus
Aurelius fits any date, so it gives nobody a reason to come back tomorrow.
What happened ON this date is unique by construction, and it is exactly
uDAY's own claim: a date has an identity. Quotes are also where a model
fabricates; events come with a URL.

The gate is the point. A history line ships ONLY if the model used its web
search and returned a source URL and a plausible year. Anything short of
that falls back to an original line that makes no factual claim, so the
account can never post an invented fact unattended.

env: GROK_API_KEY
usage: python3 tools/x_daily_line.py [MM-DD]
"""
import json, os, re, sys
from datetime import datetime, timezone, timedelta

API = "https://api.x.ai/v1/responses"
MODEL = "grok-4.20-0309-non-reasoning"
MONTHS = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC']
FULL = ['January','February','March','April','May','June','July','August',
        'September','October','November','December']

# Used when the gate rejects, when the key is absent, or when the API fails.
# They vary by date so the account does not repeat itself within a week, and
# none of them asserts a fact.
FALLBACK = [
    "Tomorrow the calendar turns again. One of these days is yours.",
    "Every date belongs to someone. This one already does.",
    "366 days exist. Only one of them is the day you think of first.",
    "A date is the smallest thing a person can own.",
    "The calendar comes back around. That is the whole promise.",
    "Some days are just dates. Some become part of a story.",
    "One day a year, this one is the only one that matters.",
]

PROMPT = """You write ONE closing line for @udaygift's daily post on X.

uDAY is an onchain art collection where every piece is a real calendar
date. Holders of a date claim that day's gift when the calendar reaches it.
The post already says today is {full} {d} and how many people hold it — so
your line must NOT repeat any of that.

Use your web search tool to find something that genuinely happened on
{full} {d} (any year). Prefer, in this order:
  1. a crypto or computing milestone on this date
  2. a widely-known historical event on this date
  3. something a well-known person documented doing or saying ON this date

Write the fact as one clean sentence, with the year, properly punctuated.
Then ONE short sentence that lands it: why this particular day is not
interchangeable with any other.

Hard rules:
- At most 150 characters TOTAL.
- Never write "now carries", "immutable", "milestone now", "this date now"
  or any variation. Those are the formula and the formula is banned. Every
  day's line must be shaped differently from a template.
- Never use the words "onchain" or "uDAY" — the post said them already.
- No hashtags, no emoji, no URLs, no @mentions, no "On this day".
- Never invent a quotation. Quote only wording you actually found; when
  unsure, describe what happened instead.

The second sentence is the hard part. It should sound like a person who
noticed something, not like a brand. Vary its shape day to day: sometimes
an observation, sometimes a consequence, sometimes plain understatement.
Never reuse a sentence pattern you would expect from an ad.

Reply with ONLY this JSON, nothing else:
{{"line": "...", "fact": "...", "year": 1920, "source": "https://..."}}

If your search found nothing solid for this date, reply exactly:
{{"line": null}}"""

# Phrases the model reaches for when it is writing an ad, plus the ones it
# proved it would copy verbatim out of this very file.
BANNED = re.compile(r"now carries|immutable|onchain|uday|milestone now|"
                    r"this date now|calendar square|square (on|of) the calendar|"
                    r"\bsquare\b|#\w|@\w", re.I)


def today_key():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%m-%d")


def _call(prompt, timeout=90):
    # requests, not urllib: it ships its own CA bundle, and urllib fails
    # certificate verification on a stock macOS python
    import requests
    r = requests.post(API, timeout=timeout,
                      headers={"Authorization": "Bearer " + os.environ["GROK_API_KEY"]},
                      json={"model": MODEL,
                            "input": [{"role": "user", "content": prompt}],
                            "tools": [{"type": "web_search"}]})
    r.raise_for_status()
    return r.json()


def _text_and_cites(resp):
    text, cites = "", []
    for o in resp.get("output") or []:
        if o.get("type") != "message":
            continue
        for c in o.get("content") or []:
            text += c.get("text") or ""
            cites += [a.get("url") for a in (c.get("annotations") or []) if a.get("url")]
    return text, cites


def line_for(day, verbose=False):
    """Returns (line, source_or_None). Never raises: a bad day still posts."""
    m, d = int(day[:2]), int(day[3:])
    idx = (m * 31 + d) % len(FALLBACK)
    safe = FALLBACK[idx]
    if not os.environ.get("GROK_API_KEY"):
        return safe, None
    prompt = PROMPT.format(full=FULL[m - 1], d=d)
    text = cites = None
    for attempt in (1, 2):
        try:
            text, cites = _text_and_cites(_call(prompt, timeout=150))
            break
        except Exception as e:
            if verbose: print("grok attempt %d failed: %s" % (attempt, e))
    if text is None:
        return safe, None

    mo = re.search(r"\{.*\}", text, re.S)
    if not mo:
        if verbose: print("no JSON in reply: %r" % text[:160])
        return safe, None
    try:
        got = json.loads(mo.group(0))
    except Exception:
        if verbose: print("unparseable JSON: %r" % mo.group(0)[:160])
        return safe, None

    line = (got.get("line") or "").strip()
    src = (got.get("source") or "").strip() or (cites[0] if cites else "")
    year = got.get("year")

    # the gate — every one of these must hold or the fact does not ship
    why = None
    if not line:                                   why = "model declined"
    elif len(line) > 170:                          why = "too long (%d)" % len(line)
    elif not src.startswith("http"):               why = "no source url"
    elif not (isinstance(year, int) and 1000 <= year <= datetime.now().year):
        why = "implausible year %r" % (year,)
    elif re.search(r"https?://|[#@]\w", line):     why = "contains a link/tag"
    elif '"' in line and not cites:                why = "quotes with nothing cited"
    elif BANNED.search(line):                      why = "used a banned formula word"
    elif not re.search(r"\b(1[0-9]{3}|20[0-2][0-9])\b", line):
        why = "the line never states the year"
    if why:
        if verbose: print("gate rejected (%s): %r" % (why, line[:120]))
        return safe, None
    return line, src


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    day = args[0] if args else today_key()
    line, src = line_for(day, verbose=True)
    print("\n%s  %s" % (MONTHS[int(day[:2]) - 1], day[3:]))
    print("  %s" % line)
    print("  source: %s" % (src or "(fallback — no factual claim made)"))
