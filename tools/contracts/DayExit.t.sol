// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import "forge-std/Test.sol";
import "../src/DayExit.sol";

contract DayExitForkTest is Test {
    address constant UDAY = 0x359211bb6b8CAbcE02DCBEc1c55B50f2EC884146;
    address constant USER = 0xE72d42810212C856636CD9d019E98cfE985535Fd;
    uint256 constant PIECE = 33008;      // one of the user's duplicate 01-06 pieces
    bytes4  constant ITEM_TRANSFER = 0x11313258;

    DayExitFactory f;

    function setUp() public {
        f = new DayExitFactory();
    }

    function _fund(address vault) internal {
        vm.prank(USER);
        (bool ok, ) = UDAY.call(abi.encodeWithSelector(ITEM_TRANSFER, vault, PIECE));
        require(ok, "item transfer failed");
    }

    function testFullExit() public {
        vm.prank(USER);
        address vault = f.createExit();
        _fund(vault);
        assertEq(IERC20Min(UDAY).balanceOf(vault), 1e18, "token should ride with the item");

        uint256 ethBefore = USER.balance;
        vm.prank(USER);
        DayExitVault(payable(vault)).execute(0);

        assertEq(IERC20Min(UDAY).balanceOf(vault), 0, "vault sold its token");
        assertEq(vault.balance, 0, "vault forwarded everything");
        assertGt(USER.balance, ethBefore, "user received ETH");
        emit log_named_uint("ETH received (wei)", USER.balance - ethBefore);
    }

    function testRescueBringsItemAndTokenBack() public {
        vm.prank(USER);
        address vault = f.createExit();
        _fund(vault);
        uint256 before = IERC20Min(UDAY).balanceOf(USER);
        vm.prank(USER);
        DayExitVault(payable(vault)).rescueItem(PIECE);
        assertEq(IERC20Min(UDAY).balanceOf(USER), before + 1e18, "item+token returned");
    }

    function testStrangerCannotExecute() public {
        vm.prank(USER);
        address vault = f.createExit();
        _fund(vault);
        vm.prank(address(0xBEEF));
        vm.expectRevert(DayExitVault.NotBeneficiary.selector);
        DayExitVault(payable(vault)).execute(0);
    }

    function testSlippageGuard() public {
        vm.prank(USER);
        address vault = f.createExit();
        _fund(vault);
        vm.prank(USER);
        vm.expectRevert();                     // absurd minOut must revert
        DayExitVault(payable(vault)).execute(1e18);
    }
}
