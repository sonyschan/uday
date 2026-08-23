// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// uDAY Claim Gift — Phase 1 (flat USDG gifts, daily merkle roots).
///
/// Design notes, matching the feasibility study of 2026-08-23:
/// - The date identity of a uDAY exists only in the off-chain index (the art
///   must be glyph-decoded), so eligibility is oracle-fed: each day a merkle
///   root of (address, amount) leaves is posted, built by the same pipeline
///   that builds uday.gift's date index. Proof files are public; that is safe
///   because claim() always pays the LEAF address, never msg.sender.
/// - Amount formula lives entirely in the root builder. Phase 1 posts flat
///   $1-per-piece leaves; Phase 2 swaps the formula to accrual-share without
///   touching this contract.
/// - The contract holds only a small owner-funded float. Unclaimed value is
///   not tracked per-day on chain; the public ledger in the site repo does
///   the accounting and the owner tops up / withdraws the float accordingly.
/// - No external dependencies; hand-rolled ownable + sorted-pair merkle.
interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function balanceOf(address who) external view returns (uint256);
}

contract UdayGift {
    address public owner;
    address public poster;              // low-privilege key (CI) allowed to post roots
    IERC20  public immutable token;     // USDG on Robinhood Chain
    uint64  public claimWindow = 48 hours;
    bool    public paused;

    struct DayRoot { bytes32 root; uint64 postedAt; }
    mapping(uint32 => DayRoot) public roots;                      // dayId = YYYYMMDD
    mapping(uint32 => mapping(address => bool)) public claimed;

    event RootPosted(uint32 indexed dayId, bytes32 root);
    event Claimed(uint32 indexed dayId, address indexed account, uint256 amount);

    error NotAuthorized();
    error AlreadyPosted();
    error NothingPosted();
    error WindowClosed();
    error AlreadyClaimed();
    error BadProof();
    error Paused();

    constructor(address usdg, address poster_) {
        owner = msg.sender;
        poster = poster_;
        token = IERC20(usdg);
    }

    modifier onlyOwner() { if (msg.sender != owner) revert NotAuthorized(); _; }

    /// One root per day, append-only: a posted root can never be replaced,
    /// so a compromised poster key can add bogus FUTURE days (bounded by the
    /// float) but can never rewrite a day people already saw.
    function setRoot(uint32 dayId, bytes32 root) external {
        if (msg.sender != poster && msg.sender != owner) revert NotAuthorized();
        if (roots[dayId].root != bytes32(0)) revert AlreadyPosted();
        roots[dayId] = DayRoot(root, uint64(block.timestamp));
        emit RootPosted(dayId, root);
    }

    /// Anyone may submit a claim; funds always go to the leaf address.
    function claim(uint32 dayId, address account, uint256 amount, bytes32[] calldata proof) external {
        if (paused) revert Paused();
        DayRoot memory d = roots[dayId];
        if (d.root == bytes32(0)) revert NothingPosted();
        if (block.timestamp > d.postedAt + claimWindow) revert WindowClosed();
        if (claimed[dayId][account]) revert AlreadyClaimed();

        bytes32 node = keccak256(abi.encodePacked(account, amount));
        for (uint256 i = 0; i < proof.length; i++) {
            bytes32 p = proof[i];
            node = node < p ? keccak256(abi.encodePacked(node, p))
                            : keccak256(abi.encodePacked(p, node));
        }
        if (node != d.root) revert BadProof();

        claimed[dayId][account] = true;
        require(token.transfer(account, amount), "transfer failed");
        emit Claimed(dayId, account, amount);
    }

    // ── owner controls ────────────────────────────────────────────────
    function withdraw(uint256 amount) external onlyOwner {
        require(token.transfer(owner, amount), "transfer failed");
    }
    function setPoster(address p) external onlyOwner { poster = p; }
    function setClaimWindow(uint64 w) external onlyOwner { claimWindow = w; }
    function setPaused(bool p) external onlyOwner { paused = p; }
    function transferOwnership(address o) external onlyOwner { owner = o; }
}
