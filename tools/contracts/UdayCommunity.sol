// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// uDAY communities — Phase A: special days and token-gated membership.
///
/// Design notes (owner, 2026-08-26):
/// - **No admins anywhere.** A community's rules are fixed at creation and can
///   never be edited, not even by its creator: a creator who could raise the
///   threshold could empty the room, which is administration by another name.
///   Want different rules? Create another community. Nobody — not the creator,
///   not uday.gift, not this contract's deployer — can eject a member.
/// - **Membership is a token balance, not a list.** You are in while you hold
///   enough of the gating token; sell it and you are out. Nothing to approve,
///   nothing to revoke. The contract checks at join; the off-chain index
///   re-checks every cycle, so a member who drops below simply stops appearing.
/// - **Joining is explicit.** Meeting the threshold makes you eligible, never a
///   member: appearing on a social calendar links your wallet to a date in
///   public, and that has to be a choice.
/// - **Special days are global**, not per-community — they are a property of a
///   person, and communities only display them. How many you may declare is
///   gated by uDAY holdings: 1 / 10 / 100 whole tokens buy 1 / 2 / 3 days.
/// - **The tier reads balanceOf, not an item count.** uToken exposes no item
///   count on chain, but items are welded 1:1 to whole tokens, so a balance is
///   an upper bound on pieces held (verified on a live holder: 251 items,
///   254.87 tokens). Generous by a few loose tokens, and it costs the same to
///   acquire either way.
/// - **This contract cannot verify that you own a piece OF that date.** A
///   uDAY's date exists only inside its art and is decoded off-chain, so the
///   chain stores your declared day and the index publishes it only if you
///   really hold that date. Declaring a day you do not own is possible here
///   and simply never renders.
interface IERC20Bal {
    function balanceOf(address) external view returns (uint256);
}

contract UdayCommunity {
    address public constant UDAY = 0x359211bb6b8CAbcE02DCBEc1c55B50f2EC884146;

    struct Community {
        address token;        // gating token (phase 1: a uToken on this chain)
        uint256 minBalance;   // wei of that token needed to join
        address creator;      // recorded for provenance only — grants nothing
        uint64  createdAt;
        string  slug;
        string  name;
    }

    mapping(bytes32 => Community) public communities;      // id = keccak(slug)
    mapping(bytes32 => mapping(address => bool)) public isMember;
    mapping(address => uint16[]) private _days;            // MMDD, recurring yearly

    // Everything the indexer needs must be READABLE, not merely emitted: this
    // chain caps eth_getLogs at 10 blocks, so scanning history for events is
    // not an option. Both lists are append-only — `seen` keeps a member after
    // they leave, and the indexer filters on isMember, which costs one extra
    // batched read and saves the contract a swap-and-pop bookkeeping mapping.
    bytes32[] private _all;
    mapping(bytes32 => address[]) private _seen;
    mapping(bytes32 => mapping(address => bool)) private _everSeen;

    event CommunityCreated(bytes32 indexed id, address indexed token,
                           uint256 minBalance, address indexed creator, string slug, string name);
    event Joined(bytes32 indexed id, address indexed member);
    event Left(bytes32 indexed id, address indexed member);
    event SpecialDaySet(address indexed who, uint16 day);
    event SpecialDayCleared(address indexed who, uint16 day);

    error SlugTaken();
    error NoSuchCommunity();
    error BadSlug();
    error BelowThreshold();
    error AlreadyMember();
    error NotMember();
    error BadDay();
    error DayAlreadySet();
    error NoSlotsLeft();
    error DayNotSet();

    // ── communities ───────────────────────────────────────────────────
    /// Anyone may create one. Its rules are frozen the moment it exists.
    function createCommunity(string calldata slug, string calldata name,
                             address token, uint256 minBalance) external returns (bytes32 id) {
        bytes memory s = bytes(slug);
        if (s.length == 0 || s.length > 32) revert BadSlug();
        for (uint256 i = 0; i < s.length; i++) {
            bytes1 c = s[i];
            bool ok = (c >= 0x61 && c <= 0x7a) || (c >= 0x30 && c <= 0x39) || c == 0x2d;
            if (!ok) revert BadSlug();                 // a-z 0-9 and '-' only
        }
        id = keccak256(s);
        if (communities[id].token != address(0)) revert SlugTaken();
        communities[id] = Community(token, minBalance, msg.sender,
                                    uint64(block.timestamp), slug, name);
        _all.push(id);
        emit CommunityCreated(id, token, minBalance, msg.sender, slug, name);
    }

    function joinWith(bytes32 id, uint16 day) external {
        _setDay(msg.sender, day);
        _join(id);
    }

    function join(bytes32 id) external { _join(id); }

    function _join(bytes32 id) internal {
        Community memory c = communities[id];
        if (c.token == address(0)) revert NoSuchCommunity();
        if (isMember[id][msg.sender]) revert AlreadyMember();
        if (IERC20Bal(c.token).balanceOf(msg.sender) < c.minBalance) revert BelowThreshold();
        isMember[id][msg.sender] = true;
        if (!_everSeen[id][msg.sender]) {
            _everSeen[id][msg.sender] = true;
            _seen[id].push(msg.sender);
        }
        emit Joined(id, msg.sender);
    }

    /// Only you can remove you. There is no other path out of a community.
    function leave(bytes32 id) external {
        if (!isMember[id][msg.sender]) revert NotMember();
        isMember[id][msg.sender] = false;
        emit Left(id, msg.sender);
    }

    // ── special days ──────────────────────────────────────────────────
    function setSpecialDay(uint16 day) external { _setDay(msg.sender, day); }

    function _setDay(address who, uint16 day) internal {
        if (!_isRealDate(day)) revert BadDay();
        uint16[] storage d = _days[who];
        for (uint256 i = 0; i < d.length; i++) if (d[i] == day) revert DayAlreadySet();
        if (d.length >= slotsOf(who)) revert NoSlotsLeft();
        d.push(day);
        emit SpecialDaySet(who, day);
    }

    function clearSpecialDay(uint16 day) external {
        uint16[] storage d = _days[msg.sender];
        for (uint256 i = 0; i < d.length; i++) {
            if (d[i] == day) {
                d[i] = d[d.length - 1];
                d.pop();
                emit SpecialDayCleared(msg.sender, day);
                return;
            }
        }
        revert DayNotSet();
    }

    /// 1 / 10 / 100 whole uDAY buy 1 / 2 / 3 days. Read live, so a wallet that
    /// sells down keeps the days it already declared but cannot add more —
    /// taking days away on a balance dip would make the calendar flicker.
    function slotsOf(address who) public view returns (uint256) {
        uint256 whole = IERC20Bal(UDAY).balanceOf(who) / 1e18;
        if (whole >= 100) return 3;
        if (whole >= 10) return 2;
        if (whole >= 1) return 1;
        return 0;
    }

    function daysOf(address who) external view returns (uint16[] memory) { return _days[who]; }

    // ── enumeration, for the off-chain index ──────────────────────────
    function allCommunities() external view returns (bytes32[] memory) { return _all; }
    function communityCount() external view returns (uint256) { return _all.length; }
    /// Everyone who has ever joined. Check isMember to see who still is.
    function seenMembers(bytes32 id) external view returns (address[] memory) { return _seen[id]; }

    function _isRealDate(uint16 mmdd) internal pure returns (bool) {
        uint16 m = mmdd / 100;
        uint16 d = mmdd % 100;
        if (m < 1 || m > 12 || d < 1) return false;
        uint8[12] memory dim = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
        return d <= dim[m - 1];               // Feb 29 is a real day in leap years
    }
}
