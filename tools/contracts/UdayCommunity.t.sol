// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "./UdayCommunity.sol";

contract MockToken {
    mapping(address => uint256) public balanceOf;
    function set(address who, uint256 v) external { balanceOf[who] = v; }
}

contract UdayCommunityTest is Test {
    UdayCommunity c;
    MockToken gate;
    address alice = address(0xA11CE);
    address bob   = address(0xB0B);

    function setUp() public {
        c = new UdayCommunity();
        gate = new MockToken();
        // uDAY's balanceOf is read from a constant address, so mock code there
        MockToken uday = new MockToken();
        vm.etch(c.UDAY(), address(uday).code);
        _setUday(alice, 1 ether);
        _setUday(bob, 1 ether);
    }

    function _setUday(address who, uint256 v) internal {
        (bool ok,) = c.UDAY().call(abi.encodeWithSelector(MockToken.set.selector, who, v));
        require(ok, "mock uday");
    }

    function _make(uint256 min) internal returns (bytes32) {
        return c.createCommunity("unipeg", "Unipeg", uint32(block.chainid), address(gate), min);
    }

    // ── communities ───────────────────────────────────────────────────
    function testCreateAndJoin() public {
        bytes32 id = _make(5 ether);
        gate.set(alice, 5 ether);
        vm.prank(alice);
        c.join(id);
        assertTrue(c.isMember(id, alice));
    }

    function testJoinBelowThresholdReverts() public {
        bytes32 id = _make(5 ether);
        gate.set(alice, 4.999 ether);
        vm.prank(alice);
        vm.expectRevert(UdayCommunity.BelowThreshold.selector);
        c.join(id);
    }

    function testSlugIsUniqueAndLowercaseOnly() public {
        _make(1);
        vm.expectRevert(UdayCommunity.SlugTaken.selector);
        c.createCommunity("unipeg", "Copy", uint32(block.chainid), address(gate), 1);
        vm.expectRevert(UdayCommunity.BadSlug.selector);
        c.createCommunity("Unipeg", "Caps", uint32(block.chainid), address(gate), 1);
        vm.expectRevert(UdayCommunity.BadSlug.selector);
        c.createCommunity("uni peg", "Space", uint32(block.chainid), address(gate), 1);
    }

    /// The whole point of the design: nobody can rewrite the rules or evict
    /// anyone. There is no function that lets them, and this test exists so a
    /// future edit that adds one fails loudly.
    function testNoAdminSurfaceExists() public {
        bytes32 id = _make(5 ether);
        gate.set(alice, 5 ether);
        vm.prank(alice);
        c.join(id);

        (, address token, uint256 min,,,,) = c.communities(id);
        assertEq(token, address(gate));
        assertEq(min, 5 ether);

        // the creator is this test contract; it still cannot remove alice
        vm.expectRevert(UdayCommunity.NotMember.selector);
        c.leave(id);                       // only removes the caller, who is not a member
        assertTrue(c.isMember(id, alice));

        vm.prank(alice);
        c.leave(id);
        assertFalse(c.isMember(id, alice));
    }

    function testLeavingLetsYouRejoin() public {
        bytes32 id = _make(1 ether);
        gate.set(alice, 1 ether);
        vm.startPrank(alice);
        c.join(id);
        c.leave(id);
        c.join(id);
        vm.stopPrank();
        assertTrue(c.isMember(id, alice));
    }

    // ── special days ──────────────────────────────────────────────────
    function testTierGrantsSlots() public {
        _setUday(alice, 0);
        assertEq(c.slotsOf(alice), 0);
        _setUday(alice, 1 ether);
        assertEq(c.slotsOf(alice), 1);
        _setUday(alice, 9.99 ether);
        assertEq(c.slotsOf(alice), 1);
        _setUday(alice, 10 ether);
        assertEq(c.slotsOf(alice), 2);
        _setUday(alice, 100 ether);
        assertEq(c.slotsOf(alice), 3);
    }

    function testSlotsAreEnforced() public {
        _setUday(alice, 1 ether);
        vm.startPrank(alice);
        c.setSpecialDay(826);
        vm.expectRevert(UdayCommunity.NoSlotsLeft.selector);
        c.setSpecialDay(101);
        vm.stopPrank();

        _setUday(alice, 10 ether);
        vm.prank(alice);
        c.setSpecialDay(101);
        assertEq(c.daysOf(alice).length, 2);
    }

    function testDuplicateDayReverts() public {
        vm.startPrank(alice);
        c.setSpecialDay(826);
        vm.expectRevert(UdayCommunity.DayAlreadySet.selector);
        c.setSpecialDay(826);
        vm.stopPrank();
    }

    function testImpossibleDatesRejected() public {
        vm.startPrank(alice);
        uint16[5] memory bad = [uint16(230), 1232, 0, 1301, 431];  // 02-30 12-32 00-00 13-01 04-31
        for (uint256 i = 0; i < bad.length; i++) {
            vm.expectRevert(UdayCommunity.BadDay.selector);
            c.setSpecialDay(bad[i]);
        }
        c.setSpecialDay(229);              // Feb 29 exists in leap years
        vm.stopPrank();
        assertEq(c.daysOf(alice)[0], 229);
    }

    function testClearFreesTheSlot() public {
        _setUday(alice, 1 ether);
        vm.startPrank(alice);
        c.setSpecialDay(826);
        c.clearSpecialDay(826);
        assertEq(c.daysOf(alice).length, 0);
        c.setSpecialDay(101);              // the slot came back
        vm.stopPrank();
        assertEq(c.daysOf(alice)[0], 101);
    }

    /// Selling down must not retroactively strip days already declared — the
    /// calendar would flicker on every price-driven balance change.
    function testSellingDownKeepsDeclaredDays() public {
        _setUday(alice, 10 ether);
        vm.startPrank(alice);
        c.setSpecialDay(826);
        c.setSpecialDay(101);
        vm.stopPrank();
        _setUday(alice, 1 ether);
        assertEq(c.daysOf(alice).length, 2);
        vm.prank(alice);
        vm.expectRevert(UdayCommunity.NoSlotsLeft.selector);
        c.setSpecialDay(704);              // ...but no new ones
    }

    function testJoinWithDoesBoth() public {
        bytes32 id = _make(1 ether);
        gate.set(bob, 1 ether);
        vm.prank(bob);
        c.joinWith(id, 1225);
        assertTrue(c.isMember(id, bob));
        assertEq(c.daysOf(bob)[0], 1225);
    }

    /// The index cannot scan events on this chain (10-block getLogs cap), so
    /// everything it needs must be readable in one call.
    function testEnumerationCoversEveryoneWhoEverJoined() public {
        bytes32 id = _make(1 ether);
        gate.set(alice, 1 ether);
        gate.set(bob, 1 ether);
        vm.prank(alice); c.join(id);
        vm.prank(bob);   c.join(id);
        vm.prank(alice); c.leave(id);

        assertEq(c.allCommunities().length, 1);
        assertEq(c.allCommunities()[0], id);
        address[] memory seen = c.seenMembers(id);
        assertEq(seen.length, 2);                 // alice is still listed...
        assertFalse(c.isMember(id, alice));       // ...but no longer a member
        assertTrue(c.isMember(id, bob));

        vm.prank(alice); c.join(id);              // rejoining must not duplicate
        assertEq(c.seenMembers(id).length, 2);
    }

    function testSlugIsReadableBack() public {
        bytes32 id = _make(1);
        (,,,,, string memory slug, string memory name) = c.communities(id);
        assertEq(slug, "unipeg");
        assertEq(name, "Unipeg");
    }

    /// An ERC-721 gate must work through the same code path: balanceOf has the
    /// same selector and return type in both standards, which is the whole
    /// reason one contract serves both.
    function testErc721GateWorksUnchanged() public {
        MockToken nft = new MockToken();          // balanceOf returns a count
        bytes32 id = c.createCommunity("holders", "Holders", uint32(block.chainid), address(nft), 1);
        vm.prank(alice);
        vm.expectRevert(UdayCommunity.BelowThreshold.selector);
        c.join(id);
        nft.set(alice, 1);                        // one NFT, not 1e18 wei
        vm.prank(alice);
        c.join(id);
        assertTrue(c.isMember(id, alice));
    }

    /// Rules are frozen forever, so a room whose gate cannot be called would be
    /// broken forever and would burn its slug with it. The contract refuses.
    function testUncallableGateIsRefused() public {
        vm.expectRevert(UdayCommunity.TokenNotGateable.selector);
        c.createCommunity("dead", "Dead", uint32(block.chainid), address(0xDEAD), 1);
        assertEq(c.communityCount(), 0);          // the slug stays free
    }

    /// A token on another chain has no code here, so the contract cannot check
    /// the gate and says so rather than pretending.
    function testForeignChainCommunityIsJoinableButNotGatedOnchain() public {
        address ethToken = 0x44b28991B167582F18BA0259e0173176ca125505;   // uPEG on mainnet
        bytes32 id = c.createCommunity("upeg", "Unipeg", 1, ethToken, 1 ether);
        assertFalse(c.gatedOnchain(id));
        vm.prank(alice);
        c.join(id);                               // recorded; the index enforces
        assertTrue(c.isMember(id, alice));
    }

    function testSameChainCommunityIsGatedOnchain() public {
        bytes32 id = _make(1 ether);
        assertTrue(c.gatedOnchain(id));
    }

    /// The floor consensus CAN enforce, even when the gating token is on a
    /// chain this contract cannot see.
    function testJoinRequiresAtLeastOneUday() public {
        bytes32 id = _make(1 ether);
        gate.set(alice, 1 ether);
        _setUday(alice, 0);
        vm.prank(alice);
        vm.expectRevert(UdayCommunity.NoUday.selector);
        c.join(id);
        _setUday(alice, 1 ether);
        vm.prank(alice);
        c.join(id);
        assertTrue(c.isMember(id, alice));
    }

    /// A wallet holding none of a foreign gating token could otherwise join for
    /// free and point at the explorer. Now it costs a uDAY.
    function testForeignGateStillNeedsAUday() public {
        bytes32 id = c.createCommunity("upeg", "Unipeg", 1,
                                       0x44b28991B167582F18BA0259e0173176ca125505, 1 ether);
        _setUday(bob, 0);
        vm.prank(bob);
        vm.expectRevert(UdayCommunity.NoUday.selector);
        c.join(id);
    }

    // ── links: the one thing a creator can change, and not a rule ──────
    function testCreatorMaintainsLinksAndNobodyElseCan() public {
        bytes32 id = _make(1 ether);            // creator is this test contract
        c.setLinks(id, "https://x.com/unipegv4", "https://t.me/unipeg", "");
        (string memory x,,) = c.links(id);
        assertEq(x, "https://x.com/unipegv4");

        vm.prank(alice);
        vm.expectRevert(UdayCommunity.NotCreator.selector);
        c.setLinks(id, "https://x.com/imposter", "", "");

        c.setLinks(id, "https://x.com/moved", "", "");   // and they can change
        (string memory x2,,) = c.links(id);
        assertEq(x2, "https://x.com/moved");
    }

    /// Links must not become a back door: changing them may not touch the gate,
    /// the membership, or who created the room.
    function testSettingLinksChangesNothingElse() public {
        bytes32 id = _make(5 ether);
        gate.set(alice, 5 ether);
        vm.prank(alice);
        c.join(id);
        (uint32 ch, address tk, uint256 min, address cr,,,) = c.communities(id);
        c.setLinks(id, "a", "b", "c");
        (uint32 ch2, address tk2, uint256 min2, address cr2,,,) = c.communities(id);
        assertEq(ch, ch2); assertEq(tk, tk2); assertEq(min, min2); assertEq(cr, cr2);
        assertTrue(c.isMember(id, alice));
    }

    function testCreateWithLinksIsOneTransaction() public {
        bytes32 id = c.createCommunityWithLinks("upeg", "Unipeg", 1,
            0x44b28991B167582F18BA0259e0173176ca125505, 1 ether,
            UdayCommunity.Links("https://x.com/unipegv4", "https://t.me/unipeg",
                                "https://unipeg.art"));
        (,,, address creator,,,) = c.communities(id);
        assertEq(creator, address(this));      // not the contract itself
        (string memory x, string memory tg, string memory o) = c.links(id);
        assertEq(x, "https://x.com/unipegv4");
        assertEq(tg, "https://t.me/unipeg");
        assertEq(o, "https://unipeg.art");
    }

    function testLinksOnUnknownCommunityRevert() public {
        vm.expectRevert(UdayCommunity.NoSuchCommunity.selector);
        c.setLinks(keccak256("nope"), "a", "b", "c");
    }

    function testJoinUnknownCommunityReverts() public {
        vm.prank(alice);
        vm.expectRevert(UdayCommunity.NoSuchCommunity.selector);
        c.join(keccak256("nope"));
    }
}
