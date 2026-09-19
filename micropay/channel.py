import json
import os
import time

from web3 import Web3

from .chains import CHAINS

ABI_PATH = os.path.join(os.path.dirname(__file__), "abi.json")
ABI = json.load(open(ABI_PATH)) if os.path.exists(ABI_PATH) else []

ERC20_ABI = [
    {"name": "approve", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "outputs": [{"type": "bool"}]},
    {"name": "balanceOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "owner", "type": "address"}], "outputs": [{"type": "uint256"}]},
]


class ChannelManager:
    """On-chain lifecycle: open, settle (provider), refund (payer)."""

    def __init__(self, chain: str, private_key: str, contract_address: str = ""):
        cfg = CHAINS[chain]
        self.chain = chain
        self.cfg = cfg
        self.w3 = Web3(Web3.HTTPProvider(cfg["rpc"], request_kwargs={"timeout": 25}))
        self.account = self.w3.eth.account.from_key(private_key)
        self.contract_address = Web3.to_checksum_address(contract_address or cfg["contract"])
        self.contract = self.w3.eth.contract(address=self.contract_address, abi=ABI)

    def _send(self, fn, value=0):
        tx = fn.build_transaction({
            "from": self.account.address,
            "value": value,
            "nonce": self.w3.eth.get_transaction_count(self.account.address, "pending"),
            "gas": 400000,
            "gasPrice": max(self.w3.eth.gas_price, self.w3.to_wei(1, "gwei")),
            "chainId": self.cfg["chain_id"],
        })
        signed = self.account.sign_transaction(tx)
        h = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        rec = self.w3.eth.wait_for_transaction_receipt(h, timeout=120)
        if rec["status"] != 1:
            raise RuntimeError(f"transaction reverted: {rec['transactionHash'].hex()}")
        return rec

    def open_channel(self, provider: str, deposit_wei: int, ttl_seconds: int = 86400,
                     token: str | None = None) -> tuple[bytes, str]:
        """Opens a channel; returns (channel_id, tx_hash). token=None -> native coin."""
        expiry = int(time.time()) + ttl_seconds
        provider = Web3.to_checksum_address(provider)
        if token:
            tok = self.w3.eth.contract(address=Web3.to_checksum_address(token), abi=ERC20_ABI)
            self._send(tok.functions.approve(self.contract_address, deposit_wei))
            rec = self._send(self.contract.functions.openChannelERC20(provider, Web3.to_checksum_address(token), deposit_wei, expiry))
        else:
            rec = self._send(self.contract.functions.openChannel(provider, expiry), value=deposit_wei)
        ev = self.contract.events.ChannelOpened().process_receipt(rec)
        channel_id = bytes(ev[0]["args"]["channelId"])
        return channel_id, rec["transactionHash"].hex()

    def get_channel(self, channel_id: bytes) -> dict:
        payer, provider, token, deposit, expiry, is_open = self.contract.functions.channels(channel_id).call()
        return {"payer": payer, "provider": provider, "token": token,
                "deposit": deposit, "expiry": expiry, "open": is_open}

    def close_with_voucher(self, channel_id: bytes, cumulative_amount: int, nonce: int,
                           data_hash: bytes, signature: str) -> str:
        sig = bytes.fromhex(signature.removeprefix("0x"))
        r, s, v = sig[:32], sig[32:64], sig[64]
        if v < 27:
            v += 27
        rec = self._send(self.contract.functions.close(channel_id, cumulative_amount, nonce, data_hash, v, r, s))
        return rec["transactionHash"].hex()

    def refund_expired(self, channel_id: bytes) -> str:
        rec = self._send(self.contract.functions.refundExpired(channel_id))
        return rec["transactionHash"].hex()
