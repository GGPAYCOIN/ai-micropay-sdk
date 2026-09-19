import hashlib
import json

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak


def data_hash(data) -> bytes:
    """Canonical SHA-256 of the data payload (matches provider side)."""
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).digest()


def receipt_message(channel_id: bytes, nonce: int, dhash: bytes) -> bytes:
    return keccak(channel_id + nonce.to_bytes(32, "big") + dhash)


def sign_receipt(private_key: str, channel_id: bytes, nonce: int, dhash: bytes) -> str:
    """Provider signs a delivery receipt — makes bad data provable/disputable."""
    msg = encode_defunct(receipt_message(channel_id, nonce, dhash))
    return Account.from_key(private_key).sign_message(msg).signature.hex()


def verify_delivery(data, expected_hash_hex: str, receipt_signature: str,
                    provider_address: str, channel_id: bytes, nonce: int) -> bool:
    """Client-side authenticity check: hash matches AND provider signed the receipt."""
    dhash = data_hash(data)
    if dhash.hex() != expected_hash_hex.removeprefix("0x"):
        return False
    msg = encode_defunct(receipt_message(channel_id, nonce, dhash))
    signer = Account.recover_message(msg, signature=bytes.fromhex(receipt_signature.removeprefix("0x")))
    return signer.lower() == provider_address.lower()
