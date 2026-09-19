// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// Permanent on-chain record of data-delivery disputes.
/// A dispute is only accepted if the provider's own signed delivery receipt is presented,
/// proving the provider committed to `promisedHash` for that channel+nonce.
contract DisputeRegistry {
    uint256 public disputeCount;

    event DisputeFiled(bytes32 indexed channelId, address indexed accuser, address indexed provider,
                       uint256 nonce, bytes32 promisedHash, bytes32 actualHash, uint256 ts);

    function fileDispute(bytes32 channelId, address provider, uint256 nonce,
                         bytes32 promisedHash, bytes32 actualHash,
                         uint8 v, bytes32 r, bytes32 s) external {
        require(promisedHash != actualHash, "hashes match - no dispute");
        bytes32 m = keccak256(abi.encodePacked(channelId, nonce, promisedHash));
        bytes32 ethHash = keccak256(abi.encodePacked("\x19Ethereum Signed Message:\n32", m));
        require(ecrecover(ethHash, v, r, s) == provider, "receipt not signed by provider");
        disputeCount++;
        emit DisputeFiled(channelId, msg.sender, provider, nonce, promisedHash, actualHash, block.timestamp);
    }
}
