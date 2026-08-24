// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// Sell this day — precision exit for a chosen uDAY piece.
///
/// µToken burns the seller's NEWEST item when a token sale drops the balance
/// below the item count; you cannot pick the victim. But items transfer with
/// their token welded on (verified on-chain: selector 0x11313258 moves the
/// item AND exactly 1.0 uDAY), so an ISOLATED holder that owns exactly one
/// item burns exactly that item when it sells its one token.
///
/// Each exit gets its own minimal-proxy vault: shared custody would let one
/// user's sale burn another user's piece (newest-first races). The vault
/// sells through the canonical Uniswap Universal Router with the pool key
/// captured from uToken's own sell flow, then forwards all ETH to the
/// beneficiary. Escape hatches let the beneficiary pull the item, token or
/// ETH back out at any time — the vault can never strand a piece.
interface IERC20Min {
    function approve(address, uint256) external returns (bool);
    function balanceOf(address) external view returns (uint256);
    function transfer(address, uint256) external returns (bool);
}

interface IPermit2 {
    function approve(address token, address spender, uint160 amount, uint48 expiration) external;
}

interface IUniversalRouter {
    function execute(bytes calldata commands, bytes[] calldata inputs, uint256 deadline) external payable;
}

// v4-periphery layouts, matched byte-for-byte to the captured calldata
struct PoolKey {
    address currency0;   // native ETH = address(0)
    address currency1;   // uDAY
    uint24  fee;         // 0 — the tax lives in the hook
    int24   tickSpacing; // 60
    address hooks;       // launchTaxHook
}

struct ExactInputSingleParams {
    PoolKey poolKey;
    bool    zeroForOne;         // false: selling currency1 (uDAY) for ETH
    uint128 amountIn;
    uint128 amountOutMinimum;
    bytes   hookData;
}

contract DayExitVault {
    address constant UDAY    = 0x359211bb6b8CAbcE02DCBEc1c55B50f2EC884146;
    address constant ROUTER  = 0x53BF6B0684Ec7eF91e1387Da3D1a1769bC5A6F77;
    address constant PERMIT2 = 0x000000000022D473030F116dDEE9F6B43aC78BA3;
    address constant HOOK    = 0xa726975b51E716708417374C39180C1f12E960cc;
    bytes4  constant ITEM_TRANSFER = 0x11313258;   // itemTransfer(address to, uint256 assetId)

    address public beneficiary;

    error AlreadyInitialized();
    error NotBeneficiary();
    error EthSendFailed();

    function initialize(address b) external {
        if (beneficiary != address(0)) revert AlreadyInitialized();
        beneficiary = b;
    }

    receive() external payable {}

    modifier onlyBeneficiary() {
        if (msg.sender != beneficiary) revert NotBeneficiary();
        _;
    }

    /// Sell every uDAY token the vault holds (normally exactly 1.0, carried
    /// in by the item transfer) for native ETH and forward it all.
    function execute(uint128 minOut) external onlyBeneficiary {
        uint256 bal = IERC20Min(UDAY).balanceOf(address(this));
        // uDAY hardwires Permit2's ERC-20 allowance to infinity (approve()
        // toward Permit2 actually REVERTS: Permit2AllowanceIsFixedAtInfinity),
        // so only the Permit2->router grant is needed.
        IPermit2(PERMIT2).approve(UDAY, ROUTER, uint160(bal), uint48(block.timestamp + 600));

        bytes memory actions = hex"060c0f";   // SWAP_EXACT_IN_SINGLE, SETTLE_ALL, TAKE_ALL
        bytes[] memory params = new bytes[](3);
        params[0] = abi.encode(ExactInputSingleParams({
            poolKey: PoolKey(address(0), UDAY, 0, 60, HOOK),
            zeroForOne: false,
            amountIn: uint128(bal),
            amountOutMinimum: minOut,
            hookData: ""
        }));
        params[1] = abi.encode(UDAY, bal);         // SETTLE_ALL(currency, amount)
        params[2] = abi.encode(address(0), minOut); // TAKE_ALL(currency, minAmount)

        bytes[] memory inputs = new bytes[](1);
        inputs[0] = abi.encode(actions, params);
        IUniversalRouter(ROUTER).execute(hex"10", inputs, block.timestamp + 300);

        _sendAllEth();
    }

    // ── escape hatches: the beneficiary can always get everything out ──
    function rescueItem(uint256 assetId) external onlyBeneficiary {
        (bool ok, ) = UDAY.call(abi.encodeWithSelector(ITEM_TRANSFER, beneficiary, assetId));
        require(ok, "item rescue failed");
    }

    function rescueToken() external onlyBeneficiary {
        IERC20Min(UDAY).transfer(beneficiary, IERC20Min(UDAY).balanceOf(address(this)));
    }

    function rescueEth() external onlyBeneficiary {
        _sendAllEth();
    }

    function _sendAllEth() internal {
        uint256 bal = address(this).balance;
        if (bal == 0) return;
        (bool ok, ) = beneficiary.call{value: bal}("");
        if (!ok) revert EthSendFailed();
    }
}

contract DayExitFactory {
    address public immutable implementation;

    event ExitCreated(address indexed user, address vault);

    constructor() {
        implementation = address(new DayExitVault());
    }

    /// EIP-1167 minimal proxy — one isolated vault per exit.
    function createExit() external returns (address vault) {
        bytes20 impl = bytes20(implementation);
        assembly {
            let ptr := mload(0x40)
            mstore(ptr, 0x3d602d80600a3d3981f3363d3d373d3d3d363d73000000000000000000000000)
            mstore(add(ptr, 0x14), impl)
            mstore(add(ptr, 0x28), 0x5af43d82803e903d91602b57fd5bf30000000000000000000000000000000000)
            vault := create(0, ptr, 0x37)
        }
        require(vault != address(0), "clone failed");
        DayExitVault(payable(vault)).initialize(msg.sender);
        emit ExitCreated(msg.sender, vault);
    }
}
