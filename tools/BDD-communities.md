# Communities — behaviour checklist (owner scenarios, 2026-08-26)

Status against branch `feat/communities`. `[x]` works today, `[ ]` is next PR,
`[!]` needs a decision before the contract is deployed (there is no second
chance: no owner, no upgrade path).

---

## 1. Logged out, homepage: a community-calendar block

> I learn that 1 uDAY + 1 community token creates a calendar of members'
> important days. CREATE asks me to connect a wallet.

- [ ] No community block exists on the homepage yet, and nothing links to `/c`.
- [x] The rule it advertises is real and enforced: `join()` reverts `NoUday`
      below 1 whole uDAY, and the community token is checked on top.
- [ ] CREATE must prompt for a wallet rather than failing silently — the form
      already refuses politely (`cnew.err.nowallet`), but it should invite.

Note: the block belongs above the composer. The page is 5.6 screens and the
composer is the least load-bearing section on it.

## 2. Header: MY CALENDAR / COMMUNITIES, and the address chip goes

> Mobile shortens them to 個人 / 社區. Both prompt for a wallet, then redirect.

- [ ] Header currently carries: language, connect, address chip, log out.
- [!] **The chip is not decoration — it is the only door to my.uday.gift**
      (`mine-wallet` sets the handoff cookie and redirects). Removing it means
      MY CALENDAR must take over that job, cookie and all, or personal mode
      breaks for everyone already logged in.
- [ ] A logged-out click on either nav item should connect first, then land on
      the destination, not drop the user on the homepage after connecting.

## 3. Logged in: a communities dashboard

> Mine / popular (by member count) / the rest. Each card shows member count,
> token symbol, short CA (click to copy), and which chain.

- [ ] Dashboard does not exist. `/c` is only the create form today.
- [!] **`symbol()` is not indexed.** One extra read per community in
      `build_communities.py`, on whichever chain the token lives — cheap, but
      it has to be added or every card says "0x44b2…".
- [x] Member count, chain, CA and gate are already in `data/communities.json`.
- [x] Copy-to-clipboard exists (`#btn-copy` pattern in the proof bar).

## 4. Opening a community from the dashboard

> Mine → calendar, shareable link. Popular → joined opens it; not joined opens
> a modal with the token to buy, how much, social links, and VIEW CALENDAR.

- [x] `/c/<slug>` renders and is already a shareable URL.
- [x] The modal's facts (token, amount, chain, who checks the gate) are indexed.
- [!] **Social links are not stored anywhere.** See the decision below.
- [ ] Modal itself is next PR.

## 5. Create form

> Chain → CA → validate on paste → ERC-20/721 → amount (default 1) → socials.

- [x] Chain picker is a DOM listbox (never a native `<select>`: wallet in-app
      browsers cannot open those).
- [x] Paste-then-probe works: ERC-165 `0x80ac58cd` for 721, `decimals()` for 20,
      and an address that cannot answer `balanceOf` is refused outright.
- [ ] Amount should default to 1.
- [!] Social links: three fields, and nowhere to put them.

## 6. Sold uDAY below 1

> In MY COMMUNITIES I see: buy a uDAY back to restore membership.

- [x] Behaviour is already correct in the data: no uDAY means no piece of any
      declared day, so the index drops the wallet from every calendar. Buying
      one back restores it next cycle with **no rejoin transaction** — on-chain
      membership was never lost.
- [!] **The dashboard cannot see this from `communities.json`.** That file lists
      only members who currently qualify; a lapsed member is simply absent, and
      absence cannot be told from never having joined.
      **Do not fix this by publishing lapsed members** — that broadcasts every
      wallet's shortfall to the world. The dashboard should read
      `isMember(id, me)` for the connected wallet (one batched call, on login,
      like the create-form probe) and compare against the published list. The
      failure state then stays visible only to the person it belongs to.

## 7. Sold the community token below its threshold

> The community still shows in MY COMMUNITIES, but as "buy back to xxx".

- [x] Same mechanism, same latency.
- [!] Same visibility problem and the same fix as 6.

Latency for 6 and 7: owners are refreshed in full every index run, so the exit
lands on the next build — **typically 15-20 minutes, up to about an hour with
GitHub Actions cron jitter.** Never promise 15 in copy.

---

## The one decision that blocks deployment

Social links need a home. Options:

1. **Immutable, set at creation** — matches the "nothing can change" promise,
   and guarantees a dead link the day a community moves or its account is
   banned. Permanent.
2. **Creator-editable** — practical, and narrow: it touches links, never the
   gate, never membership, never who is in the room. A creator could point them
   somewhere malicious later, but a creator could equally do that on day one, so
   mutability extends *when* the risk can be taken, it does not create it.
3. **Off-chain** — no contract change, but then there is no trustworthy source
   for them at all and the modal in scenario 4 has nothing to show.

**Recommended: 2, with the page labelling them as creator-set.** The immutability
claim stays scoped to rules and membership, which is where it actually matters,
and the honest sentence on the page becomes: *rules can never change; links are
maintained by whoever made the room.*

Everything else on this list is UI or indexing and can ship after deployment.
