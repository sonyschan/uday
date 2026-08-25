#!/bin/bash
# CI gift publish — build today's merkle root and post it with the POSTER key.
# Runs daily from .github/workflows/post-gift.yml just after 00:00 UTC+8;
# tools/post-gift.sh remains the manual fallback (owner keystore, local only).
#
# The poster key is LOW-PRIVILEGE by contract design: setRoot is append-only
# (a posted day can never be replaced) and the contract holds only a small
# float — a leaked key can post bogus FUTURE days at worst, never rewrite one.
#
# env: ROBINHOOD_RPC_URL (optional, public RPC fallback)
#      POSTER_PRIVATE_KEY (required to send)
set -euo pipefail
cd "$(dirname "$0")/.."

GIFT=0xBd17Ad7CD5586E8e42a73111c63A1B09985B1f09
RPC="${ROBINHOOD_RPC_URL:-https://rpc.mainnet.chain.robinhood.com/rpc}"
ZERO=0x0000000000000000000000000000000000000000000000000000000000000000

# Build today's root (today in UTC+8 — the builder owns the date math).
# "no dated pieces" is a quiet day, not a failure.
if ! OUT=$(python3 tools/build_gift_root.py 2>&1); then
  echo "$OUT"
  grep -q "no dated pieces" <<<"$OUT" && exit 0
  exit 1
fi
echo "$OUT"

DAYID=$(grep -o "setRoot(uint32,bytes32)' [0-9]*" <<<"$OUT" | awk '{print $2}')
ROOT=$(grep -o '0x[0-9a-f]\{64\}' <<<"$OUT" | head -1)
[ -n "$DAYID" ] && [ -n "$ROOT" ] || { echo "could not parse builder output"; exit 1; }

# Idempotent against a manual post or a rerun: setRoot is one-shot per day.
CUR=$(cast call "$GIFT" 'roots(uint32)(bytes32,uint64)' "$DAYID" --rpc-url "$RPC" | head -1)
if [ "$CUR" != "$ZERO" ]; then
  if [ "$CUR" = "$ROOT" ]; then
    echo "day $DAYID already posted with this exact root — keeping the proof file"
    exit 0
  fi
  # A different root is live (posted from an earlier index state). Our rebuilt
  # proofs would NOT verify against it — discard them rather than serve lies.
  echo "day $DAYID already posted with a DIFFERENT root ($CUR) — discarding rebuild"
  git checkout -- data/gift
  exit 0
fi

echo "posting root for day $DAYID ..."
cast send "$GIFT" 'setRoot(uint32,bytes32)' "$DAYID" "$ROOT" \
  --rpc-url "$RPC" --private-key "$POSTER_PRIVATE_KEY"
echo "root on-chain for day $DAYID"
