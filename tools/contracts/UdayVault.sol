// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
/// Lock a day — a piece you cannot sell until you said you could.
///
/// Why a contract and not a flag: uDAY is a µToken. A sale is a plain ERC-20
/// transfer, nothing can veto it, and when the balance drops below the item
/// count the token burns the seller's NEWEST piece — the seller does not pick
/// the victim. So a star (a declaration on UdayCommunity) protects nothing,
/// and the only lock that exists is custody: the piece has to leave the
/// wallet. Items move with their 1.0 uDAY welded on (DayExit proved a
/// contract can hold one and hand it back), so this contract holds pieces
/// for their owners and refuses to return them before a time the owner
/// chose. It never sells, never does an ERC-20 transfer, and has no admin,
/// pause or upgrade: the promise "nobody, not even us" is only worth
/// something if the code cannot be changed to break it.
///
/// One shared contract, not a vault per user: attribution is per item
/// (`slots[assetId]`), which is exactly what the index needs to paint a
/// locked piece as its owner's, and the only way custody could be mixed up
/// is an ERC-20 transfer out — there is none.
///
/// Deposit is one transaction after a one-time `setAssetOperator(vault,
/// true)` on the token: the vault pulls the item with
/// `transferAssetBackedTokenFrom`, so an item can only enter through a
/// path that records whose it is. A piece sent here by plain item transfer
/// cannot be attributed and stays — always deposit through the app.
interface IUdayItems {
    function isAssetOwner(address owner, uint256 assetId) external view returns (bool);
    function transferAssetBackedToken(address to, uint256 assetId) external;
    function transferAssetBackedTokenFrom(address from, address to, uint256 assetId) external;
}

contract UdayVault {
    address public constant UDAY = 0x359211bb6b8CAbcE02DCBEc1c55B50f2EC884146;
    /// A lock is a promise with a date on it; a typo of one extra zero must
    /// not become a piece nobody can ever get back.
    uint64 public constant MAX_LOCK = 4 * 366 days;

    struct Slot { address owner; uint64 until; }
    mapping(uint256 => Slot) public slots;          // assetId -> who, until when
    mapping(address => uint256[]) private _items;   // owner -> assetIds held here
    mapping(uint256 => uint256) private _pos;       // assetId -> index in owner's list
    uint256 public totalHeld;

    event Locked(address indexed owner, uint256 indexed assetId, uint64 until);
    event Extended(address indexed owner, uint256 indexed assetId, uint64 until);
    event Withdrawn(address indexed owner, uint256 indexed assetId);

    error NotYours();
    error AlreadyHeld();
    error StillLocked(uint64 until);
    error TooLong();
    error NotLater();
    error TransferFailed();

    /// Pull `assetId` from the caller and hold it until `until` (a unix
    /// time; 0 or the past means "held, withdrawable any time" — custody
    /// with no date is still custody: it takes the piece out of the burn
    /// order of every sale the wallet makes).
    function deposit(uint256 assetId, uint64 until) external {
        if (slots[assetId].owner != address(0)) revert AlreadyHeld();
        if (!IUdayItems(UDAY).isAssetOwner(msg.sender, assetId)) revert NotYours();
        if (until > block.timestamp + MAX_LOCK) revert TooLong();
        IUdayItems(UDAY).transferAssetBackedTokenFrom(msg.sender, address(this), assetId);
        if (!IUdayItems(UDAY).isAssetOwner(address(this), assetId)) revert TransferFailed();
        slots[assetId] = Slot(msg.sender, until);
        _pos[assetId] = _items[msg.sender].length;
        _items[msg.sender].push(assetId);
        totalHeld++;
        emit Locked(msg.sender, assetId, until);
    }

    /// Push the date later. Never earlier: a lock that can be shortened is
    /// not a lock, it is a note.
    function extend(uint256 assetId, uint64 until) external {
        Slot storage s = slots[assetId];
        if (s.owner != msg.sender) revert NotYours();
        if (until <= s.until) revert NotLater();
        if (until > block.timestamp + MAX_LOCK) revert TooLong();
        s.until = until;
        emit Extended(msg.sender, assetId, until);
    }

    /// The piece goes home, its 1.0 uDAY with it.
    function withdraw(uint256 assetId) external {
        Slot memory s = slots[assetId];
        if (s.owner != msg.sender) revert NotYours();
        if (block.timestamp < s.until) revert StillLocked(s.until);
        delete slots[assetId];
        _remove(msg.sender, assetId);
        totalHeld--;
        IUdayItems(UDAY).transferAssetBackedToken(msg.sender, assetId);
        if (!IUdayItems(UDAY).isAssetOwner(msg.sender, assetId)) revert TransferFailed();
        emit Withdrawn(msg.sender, assetId);
    }

    // ── views for the index and the page ──
    function itemsOf(address owner) external view returns (uint256[] memory) { return _items[owner]; }
    function countOf(address owner) external view returns (uint256) { return _items[owner].length; }
    function ownerOf(uint256 assetId) external view returns (address) { return slots[assetId].owner; }
    function unlockAt(uint256 assetId) external view returns (uint64) { return slots[assetId].until; }

    function _remove(address owner, uint256 assetId) internal {
        uint256[] storage list = _items[owner];
        uint256 i = _pos[assetId];
        uint256 last = list.length - 1;
        if (i != last) {
            uint256 moved = list[last];
            list[i] = moved;
            _pos[moved] = i;
        }
        list.pop();
        delete _pos[assetId];
    }
}
