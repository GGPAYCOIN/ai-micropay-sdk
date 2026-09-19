// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IERC20 {
    function transferFrom(address, address, uint256) external returns (bool);
    function transfer(address, uint256) external returns (bool);
}

/// Unidirectional payment channel for AI-agent pay-per-query data purchases.
contract MicropayChannel {
    struct Channel {
        address payer;
        address provider;
        address token; // address(0) = native coin
        uint128 deposit;
        uint64 expiry;
        bool open;
    }

    mapping(bytes32 => Channel) public channels;
    uint256 public channelCount;
    bytes32 public immutable DOMAIN_SEPARATOR;
    bytes32 public constant VOUCHER_TYPEHASH =
        keccak256("MicroVoucher(bytes32 channelId,uint256 cumulativeAmount,uint256 nonce,bytes32 dataHash)");

    event ChannelOpened(bytes32 indexed channelId, address indexed payer, address indexed provider, address token, uint256 deposit, uint64 expiry);
    event ChannelClosed(bytes32 indexed channelId, uint256 paidToProvider, uint256 refundedToPayer);

    constructor() {
        DOMAIN_SEPARATOR = keccak256(abi.encode(
            keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"),
            keccak256(bytes("DataMicropayEngine")),
            keccak256(bytes("1")),
            block.chainid,
            address(this)
        ));
    }

    function openChannel(address provider, uint64 expiry) external payable returns (bytes32 id) {
        require(msg.value > 0 && expiry > block.timestamp && provider != address(0), "bad params");
        id = keccak256(abi.encodePacked(msg.sender, provider, channelCount++));
        channels[id] = Channel(msg.sender, provider, address(0), uint128(msg.value), expiry, true);
        emit ChannelOpened(id, msg.sender, provider, address(0), msg.value, expiry);
    }

    function openChannelERC20(address provider, address token, uint256 amount, uint64 expiry) external returns (bytes32 id) {
        require(amount > 0 && expiry > block.timestamp && provider != address(0), "bad params");
        require(IERC20(token).transferFrom(msg.sender, address(this), amount), "transferFrom failed");
        id = keccak256(abi.encodePacked(msg.sender, provider, channelCount++));
        channels[id] = Channel(msg.sender, provider, token, uint128(amount), expiry, true);
        emit ChannelOpened(id, msg.sender, provider, token, amount, expiry);
    }

    /// Provider settles with the latest payer-signed voucher.
    function close(bytes32 id, uint256 cumulativeAmount, uint256 nonce, bytes32 dataHash, uint8 v, bytes32 r, bytes32 s) external {
        Channel storage c = channels[id];
        require(c.open, "channel closed");
        require(msg.sender == c.provider, "only provider");
        bytes32 digest = keccak256(abi.encodePacked(
            "\x19\x01", DOMAIN_SEPARATOR,
            keccak256(abi.encode(VOUCHER_TYPEHASH, id, cumulativeAmount, nonce, dataHash))
        ));
        require(ecrecover(digest, v, r, s) == c.payer, "bad signature");
        uint256 pay = cumulativeAmount > c.deposit ? c.deposit : cumulativeAmount;
        uint256 refund = uint256(c.deposit) - pay;
        c.open = false;
        _payout(c.token, c.provider, pay);
        _payout(c.token, c.payer, refund);
        emit ChannelClosed(id, pay, refund);
    }

    /// Payer reclaims full deposit if provider never settled before expiry.
    function refundExpired(bytes32 id) external {
        Channel storage c = channels[id];
        require(c.open && block.timestamp > c.expiry, "not refundable");
        require(msg.sender == c.payer, "only payer");
        c.open = false;
        _payout(c.token, c.payer, c.deposit);
        emit ChannelClosed(id, 0, c.deposit);
    }

    function _payout(address token, address to, uint256 amt) internal {
        if (amt == 0) return;
        if (token == address(0)) {
            (bool ok, ) = to.call{value: amt}("");
            require(ok, "native send failed");
        } else {
            require(IERC20(token).transfer(to, amt), "transfer failed");
        }
    }
}
