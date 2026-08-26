#!/bin/bash
# Prove the deployed UdayCommunity is this repo's source.
#
#   bash tools/verify-community.sh
#
# Robinhood Chain has no working source verification (Blockscout errors,
# Sourcify does not carry the chain), so "no admin, not even the dev" is a
# claim nobody could check. This makes it checkable by anyone, with nothing
# but foundry and the public RPC.
#
# Solidity appends a CBOR metadata trailer holding a hash of the source paths
# and compiler settings, so two identical contracts compiled in different
# directories differ in their last few dozen bytes. The EXECUTABLE code before
# that trailer is what has to match, and it must match exactly.
set -euo pipefail
cd "$(dirname "$0")/.."

ADDR=${1:-$(cat data/community-contract.txt 2>/dev/null || true)}
RPC=${ROBINHOOD_RPC_URL:-https://rpc.mainnet.chain.robinhood.com/rpc}
[ -n "$ADDR" ] || { echo "usage: bash tools/verify-community.sh [address]"; exit 1; }

echo "contract : $ADDR"
echo "rpc      : ${RPC%%\?*}"
echo "source   : tools/contracts/UdayCommunity.sol"
echo

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
forge init "$TMP/p" --no-git -q
cp tools/contracts/UdayCommunity.sol "$TMP/p/src/"
rm -f "$TMP/p/src/Counter.sol" "$TMP/p/test/Counter.t.sol"
rm -rf "$TMP/p/script"
(cd "$TMP/p" && forge build -q)

cast code "$ADDR" --rpc-url "$RPC" > "$TMP/onchain.hex"

python3 - "$TMP" <<'PY'
import json, sys, os
tmp = sys.argv[1]
local = json.load(open(os.path.join(tmp, "p/out/UdayCommunity.sol/UdayCommunity.json")))
local = local["deployedBytecode"]["object"]
chain = open(os.path.join(tmp, "onchain.hex")).read().strip()

def strip_metadata(code):
    """The last two bytes are the CBOR trailer's length; drop the trailer."""
    if len(code) < 8:
        return code
    n = int(code[-4:], 16)
    end = len(code) - 4 - n * 2
    return code[:end] if 0 < end < len(code) else code

a, b = strip_metadata(local), strip_metadata(chain)
print("executable bytes  local %d  chain %d" % (len(a) // 2, len(b) // 2))
if a == b:
    print()
    print("MATCH — the deployed contract is compiled from this source.")
    print("There is no owner, no pause and no upgrade path in it, and you have")
    print("just confirmed that for yourself rather than taking anyone's word.")
    sys.exit(0)
print()
print("MISMATCH — the deployed contract is NOT this source.")
n = min(len(a), len(b))
i = next((k for k in range(n) if a[k] != b[k]), n)
print("  first difference at byte %d" % (i // 2))
sys.exit(1)
PY
