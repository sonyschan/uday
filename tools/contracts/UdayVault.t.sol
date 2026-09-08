// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import "forge-std/Test.sol";
import "../src/UdayVault.sol";

interface IERC20View { function balanceOf(address) external view returns (uint256); }
interface IOperator { function setAssetOperator(address op, bool on) external; }

/// Runs against a fork of Robinhood Chain: the token's item semantics are the
/// thing under test, and no mock can be trusted to burn the newest piece.
contract UdayVaultForkTest is Test {
    address constant UDAY = 0x359211bb6b8CAbcE02DCBEc1c55B50f2EC884146;
    address constant USER = 0xE72d42810212C856636CD9d019E98cfE985535Fd;
    uint256 constant PIECE = 33008;    // one of the user's duplicate 01-06 pieces
    uint256 constant PIECE2 = 32667;   // 08-22, plate + frame
    UdayVault v;

    function setUp() public {
        v = new UdayVault();
        vm.prank(USER);
        IOperator(UDAY).setAssetOperator(address(v), true);
    }

    function _deposit(uint256 id, uint64 until) internal {
        vm.prank(USER);
        v.deposit(id, until);
    }

    function testDepositMovesItemAndToken() public {
        uint256 before = IERC20View(UDAY).balanceOf(USER);
        _deposit(PIECE, uint64(block.timestamp + 30 days));
        assertTrue(IUdayItems(UDAY).isAssetOwner(address(v), PIECE), "vault holds the item");
        assertFalse(IUdayItems(UDAY).isAssetOwner(USER, PIECE), "user no longer does");
        assertEq(IERC20View(UDAY).balanceOf(address(v)), 1e18, "1.0 uDAY rode with it");
        assertEq(IERC20View(UDAY).balanceOf(USER), before - 1e18);
        assertEq(v.ownerOf(PIECE), USER);
        assertEq(v.countOf(USER), 1);
        assertEq(v.totalHeld(), 1);
    }

    function testWithdrawRefusedWhileLocked() public {
        uint64 until = uint64(block.timestamp + 30 days);
        _deposit(PIECE, until);
        vm.prank(USER);
        vm.expectRevert(abi.encodeWithSelector(UdayVault.StillLocked.selector, until));
        v.withdraw(PIECE);
    }

    function testWithdrawAfterUnlockReturnsItemAndToken() public {
        uint64 until = uint64(block.timestamp + 30 days);
        _deposit(PIECE, until);
        uint256 before = IERC20View(UDAY).balanceOf(USER);
        vm.warp(until);
        vm.prank(USER);
        v.withdraw(PIECE);
        assertTrue(IUdayItems(UDAY).isAssetOwner(USER, PIECE), "item is back");
        assertEq(IERC20View(UDAY).balanceOf(USER), before + 1e18, "token is back");
        assertEq(IERC20View(UDAY).balanceOf(address(v)), 0);
        assertEq(v.ownerOf(PIECE), address(0));
        assertEq(v.countOf(USER), 0);
        assertEq(v.totalHeld(), 0);
    }

    function testNoDateMeansWithdrawAnyTime() public {
        _deposit(PIECE, 0);
        vm.prank(USER);
        v.withdraw(PIECE);
        assertTrue(IUdayItems(UDAY).isAssetOwner(USER, PIECE));
    }

    function testStrangerCannotWithdrawOrExtend() public {
        _deposit(PIECE, 0);
        vm.startPrank(address(0xBEEF));
        vm.expectRevert(UdayVault.NotYours.selector);
        v.withdraw(PIECE);
        vm.expectRevert(UdayVault.NotYours.selector);
        v.extend(PIECE, uint64(block.timestamp + 1 days));
        vm.stopPrank();
    }

    function testCannotDepositSomeoneElsesPiece() public {
        vm.prank(address(0xBEEF));
        vm.expectRevert(UdayVault.NotYours.selector);
        v.deposit(PIECE, 0);
    }

    function testDepositWithoutOperatorReverts() public {
        vm.prank(USER);
        IOperator(UDAY).setAssetOperator(address(v), false);
        vm.prank(USER);
        vm.expectRevert();
        v.deposit(PIECE, 0);
        assertTrue(IUdayItems(UDAY).isAssetOwner(USER, PIECE), "nothing moved");
    }

    function testExtendOnlyForward() public {
        uint64 until = uint64(block.timestamp + 30 days);
        _deposit(PIECE, until);
        vm.startPrank(USER);
        vm.expectRevert(UdayVault.NotLater.selector);
        v.extend(PIECE, until - 1);
        v.extend(PIECE, until + 1 days);
        assertEq(v.unlockAt(PIECE), until + 1 days);
        uint64 tooFar = uint64(block.timestamp) + v.MAX_LOCK() + 1;   // read BEFORE arming expectRevert
        vm.expectRevert(UdayVault.TooLong.selector);
        v.extend(PIECE, tooFar);
        vm.stopPrank();
    }

    function testTooLongRejectedAtDeposit() public {
        uint64 tooFar = uint64(block.timestamp) + v.MAX_LOCK() + 1;
        vm.prank(USER);
        vm.expectRevert(UdayVault.TooLong.selector);
        v.deposit(PIECE, tooFar);
    }

    function testDoubleDepositReverts() public {
        _deposit(PIECE, 0);
        vm.prank(USER);
        vm.expectRevert();        // the token refuses: the user is no longer the owner
        v.deposit(PIECE, 0);
    }

    function testEnumerationSurvivesSwapRemove() public {
        _deposit(PIECE, 0);
        _deposit(PIECE2, 0);
        uint256[] memory a = v.itemsOf(USER);
        assertEq(a.length, 2);
        vm.prank(USER);
        v.withdraw(PIECE);
        uint256[] memory b = v.itemsOf(USER);
        assertEq(b.length, 1);
        assertEq(b[0], PIECE2);
        assertEq(v.ownerOf(PIECE2), USER);
    }

    /// The reason the vault exists: with the piece inside, a sale from the
    /// wallet cannot burn it. The wallet sells one whole token; the burn
    /// lands on whatever the wallet still holds, never on the vaulted piece.
    function testVaultedPieceSurvivesAWalletSale() public {
        _deposit(PIECE2, uint64(block.timestamp + 365 days));
        // simulate the sale's effect: a plain ERC-20 transfer of 1.0 out of the wallet
        vm.prank(USER);
        (bool ok, ) = UDAY.call(abi.encodeWithSignature("transfer(address,uint256)", address(0xCAFE), 1e18));
        assertTrue(ok, "transfer went through");
        assertTrue(IUdayItems(UDAY).isAssetOwner(address(v), PIECE2), "vaulted piece untouched");
        assertEq(IERC20View(UDAY).balanceOf(address(v)), 1e18);
    }
}
