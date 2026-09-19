from eth_account import Account
from eth_account.messages import encode_typed_data


class VoucherSigner:
    """EIP-712 off-chain micro-voucher signer (zero gas per query)."""

    def __init__(self, private_key: str, chain_id: int, verifying_contract: str):
        self.account = Account.from_key(private_key)
        self.chain_id = chain_id
        self.verifying_contract = verifying_contract

    @property
    def address(self) -> str:
        return self.account.address

    def typed_voucher(self, channel_id: bytes, cumulative_amount: int, nonce: int, data_hash: bytes) -> dict:
        return {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "MicroVoucher": [
                    {"name": "channelId", "type": "bytes32"},
                    {"name": "cumulativeAmount", "type": "uint256"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "dataHash", "type": "bytes32"},
                ],
            },
            "primaryType": "MicroVoucher",
            "domain": {
                "name": "DataMicropayEngine",
                "version": "1",
                "chainId": self.chain_id,
                "verifyingContract": self.verifying_contract,
            },
            "message": {
                "channelId": channel_id,
                "cumulativeAmount": cumulative_amount,
                "nonce": nonce,
                "dataHash": data_hash,
            },
        }

    def sign_voucher(self, channel_id: bytes, cumulative_amount: int, nonce: int, data_hash: bytes) -> str:
        msg = encode_typed_data(full_message=self.typed_voucher(channel_id, cumulative_amount, nonce, data_hash))
        return self.account.sign_message(msg).signature.hex()


def recover_voucher_signer(chain_id: int, verifying_contract: str, channel_id: bytes,
                           cumulative_amount: int, nonce: int, data_hash: bytes, signature: str) -> str:
    """Provider-side: recover the payer address from a voucher signature."""
    signer = VoucherSigner.__new__(VoucherSigner)
    signer.chain_id = chain_id
    signer.verifying_contract = verifying_contract
    typed = VoucherSigner.typed_voucher(signer, channel_id, cumulative_amount, nonce, data_hash)
    msg = encode_typed_data(full_message=typed)
    return Account.recover_message(msg, signature=bytes.fromhex(signature.removeprefix("0x")))
