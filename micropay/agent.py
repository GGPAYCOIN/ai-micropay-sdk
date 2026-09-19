import hashlib
import time

import requests

from .chains import CHAINS
from .channel import ChannelManager
from .verifier import verify_delivery
from .wallet import VoucherSigner


class BudgetExceeded(Exception):
    pass


class DataIntegrityError(Exception):
    pass


class AutonomousDataAgent:
    """Fully autonomous pay-per-query data buyer for AI agents.

    open_channel() locks a budget on-chain once; every query() after that is an
    off-chain EIP-712 voucher — millisecond-fast, zero gas.
    """

    def __init__(self, private_key: str, chain: str = "gg", contract_address: str = "",
                 daily_budget_wei: int | None = None):
        self.chain = chain
        self.cfg = CHAINS[chain]
        self.channels = ChannelManager(chain, private_key, contract_address)
        self.signer = VoucherSigner(private_key, self.cfg["chain_id"],
                                    contract_address or self.cfg["contract"])
        self.channel_id: bytes | None = None
        self.provider_address: str | None = None
        self.nonce = 0
        self.cumulative_amount = 0
        self.daily_budget_wei = daily_budget_wei
        self._day = time.strftime("%Y-%m-%d")
        self._spent_today = 0

    @property
    def address(self) -> str:
        return self.signer.address

    def open_channel(self, provider_address: str, deposit_wei: int, ttl_seconds: int = 86400,
                     token: str | None = None) -> str:
        self.channel_id, tx = self.channels.open_channel(provider_address, deposit_wei, ttl_seconds, token)
        self.provider_address = provider_address
        self.nonce = 0
        self.cumulative_amount = 0
        return tx

    def _budget_guard(self, amount: int):
        today = time.strftime("%Y-%m-%d")
        if today != self._day:
            self._day, self._spent_today = today, 0
        if self.daily_budget_wei is not None and self._spent_today + amount > self.daily_budget_wei:
            raise BudgetExceeded(f"daily budget {self.daily_budget_wei} wei would be exceeded")
        self._spent_today += amount

    def query_node(self, endpoint_url: str, query: dict, price_per_query_wei: int, timeout: int = 30) -> dict:
        if self.channel_id is None:
            raise RuntimeError("open_channel() first")
        self._budget_guard(price_per_query_wei)
        import json as _json
        qhash = hashlib.sha256(_json.dumps(query, sort_keys=True, separators=(",", ":")).encode()).digest()
        self.nonce += 1
        self.cumulative_amount += price_per_query_wei
        signature = self.signer.sign_voucher(self.channel_id, self.cumulative_amount, self.nonce, qhash)
        payload = {
            "chain": self.chain,
            "query": query,
            "channel_id": self.channel_id.hex(),
            "cumulative_amount": str(self.cumulative_amount),
            "nonce": self.nonce,
            "query_hash": qhash.hex(),
            "signature": signature,
        }
        r = requests.post(f"{endpoint_url.rstrip('/')}/get-data", json=payload, timeout=timeout)
        body = r.json()
        if r.status_code != 200 or not body.get("ok"):
            # roll back the voucher we minted for a failed query
            self.nonce -= 1
            self.cumulative_amount -= price_per_query_wei
            self._spent_today -= price_per_query_wei
            raise RuntimeError(f"query failed: {body.get('error', r.text[:200])}")
        if not verify_delivery(body["data"], body["data_hash"], body["receipt_signature"],
                               body["provider_address"], self.channel_id, self.nonce):
            dispute_tx = None
            try:
                dispute_tx = self.file_dispute(body["data"], body["data_hash"], body["receipt_signature"])
            except Exception:
                pass
            raise DataIntegrityError(
                "provider returned data that does not match its signed receipt — session terminated"
                + (f"; on-chain dispute filed: {dispute_tx}" if dispute_tx else ""))
        return body["data"]

    def file_dispute(self, data, promised_hash_hex: str, receipt_signature: str) -> str:
        """Record the provider's broken receipt on-chain (DisputeRegistry)."""
        from .dispute import file_dispute
        from .verifier import data_hash as _dh
        dispute_addr = self.cfg.get("dispute")
        if not dispute_addr:
            raise RuntimeError("no dispute registry configured for this chain")
        return file_dispute(self.channels, dispute_addr, self.channel_id, self.provider_address,
                            self.nonce, bytes.fromhex(promised_hash_hex.removeprefix("0x")),
                            _dh(data), receipt_signature)

    def refund_expired(self) -> str:
        return self.channels.refund_expired(self.channel_id)
