DISPUTE_ABI = [
    {"name": "fileDispute", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "channelId", "type": "bytes32"}, {"name": "provider", "type": "address"},
                {"name": "nonce", "type": "uint256"}, {"name": "promisedHash", "type": "bytes32"},
                {"name": "actualHash", "type": "bytes32"}, {"name": "v", "type": "uint8"},
                {"name": "r", "type": "bytes32"}, {"name": "s", "type": "bytes32"}],
     "outputs": []},
    {"name": "disputeCount", "type": "function", "stateMutability": "view", "inputs": [],
     "outputs": [{"type": "uint256"}]},
]


def file_dispute(channel_manager, dispute_address: str, channel_id: bytes, provider: str,
                 nonce: int, promised_hash: bytes, actual_hash: bytes, receipt_signature: str) -> str:
    """File a permanent on-chain dispute using the provider's own signed receipt as evidence."""
    from web3 import Web3
    sig = bytes.fromhex(receipt_signature.removeprefix("0x"))
    r, s, v = sig[:32], sig[32:64], sig[64]
    if v < 27:
        v += 27
    c = channel_manager.w3.eth.contract(address=Web3.to_checksum_address(dispute_address), abi=DISPUTE_ABI)
    rec = channel_manager._send(c.functions.fileDispute(
        channel_id, Web3.to_checksum_address(provider), nonce, promised_hash, actual_hash, v, r, s))
    return rec["transactionHash"].hex()
