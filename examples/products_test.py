#!/usr/bin/env python3
"""Tests: multi-product purchases, underpaid rejection, budget circuit breaker, on-chain dispute."""
import json
import secrets
import sys
import time

sys.path.insert(0, "/opt/ai-datanode")
import requests
from web3 import Web3

from micropay import AutonomousDataAgent, BudgetExceeded, CHAINS
from micropay.dispute import DISPUTE_ABI, file_dispute
from micropay.verifier import receipt_message
from eth_account import Account
from eth_account.messages import encode_defunct

CONTRACTS = json.load(open("/opt/ai-datanode/contracts.json"))
CHAINS["qumtam"]["contract"] = CONTRACTS["qumtam"]
CHAINS["qumtam"]["rpc"] = "http://127.0.0.1:8547"
NODE = "https://qumtamchain.com/api/datanode"
FUNDER = open("/opt/ggstack-demo/sequencer.key").read().strip()

info = requests.get(f"{NODE}/info", timeout=15).json()
P_INTEL = int(info["products"]["security_intel"]["qumtam"])
P_WALLET = int(info["products"]["wallet_risk"]["qumtam"])
P_CHAIN = int(info["products"]["chain_health"]["qumtam"])

w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:8547"))
funder = w3.eth.account.from_key(FUNDER)
key = "0x" + secrets.token_hex(32)
addr = Account.from_key(key).address
tx = {"to": addr, "value": w3.to_wei("0.05", "ether"), "gas": 21000,
      "gasPrice": max(w3.eth.gas_price, w3.to_wei(1, "gwei")),
      "nonce": w3.eth.get_transaction_count(funder.address, "pending"), "chainId": 424242}
w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(funder.sign_transaction(tx).raw_transaction), timeout=120)

agent = AutonomousDataAgent(key, chain="qumtam", daily_budget_wei=P_WALLET + P_CHAIN + P_INTEL)  # exactly 3 queries
agent.open_channel(info["provider_address"], (P_WALLET + P_CHAIN + P_INTEL) * 2, ttl_seconds=3600)
print("channel:", agent.channel_id.hex())

# 1. wallet_risk product (live scan, 0.005)
t0 = time.time()
d = agent.query_node(NODE, {"type": "wallet_risk", "network": "eth",
                            "address": "0x28C6c06298d514Db089934071355E5743bf21d60"}, P_WALLET, timeout=90)
print(f"TEST1 wallet_risk: found={d.get('found')} risk={d.get('risk_score')} {d.get('risk_level')} "
      f"flags={len(d.get('flags', []))} [{round(time.time()-t0, 1)}s] -> PASS" if d.get("found") else f"TEST1 FAIL {d}")

# 2. chain_health product (0.003)
t0 = time.time()
d = agent.query_node(NODE, {"type": "chain_health", "network": "gg"}, P_CHAIN, timeout=120)
print(f"TEST2 chain_health: found={d.get('found')} score={d.get('score')} grade={d.get('grade')} "
      f"producers={d.get('producers')} [{round(time.time()-t0, 1)}s] -> PASS" if d.get("found") else f"TEST2 FAIL {d}")

# 3. underpaid: try to buy wallet_risk at intel price -> must be rejected + voucher rolled back
try:
    agent.query_node(NODE, {"type": "wallet_risk", "network": "eth",
                            "address": "0x28C6c06298d514Db089934071355E5743bf21d60"}, P_INTEL, timeout=60)
    print("TEST3 underpaid: FAIL (was accepted!)")
except RuntimeError as e:
    print(f"TEST3 underpaid rejected: PASS ({str(e)[:70]}…)")

# 4. budget circuit breaker: next intel query exceeds daily budget
agent.query_node(NODE, {"type": "security_intel", "network": "eth",
                        "address": "0xdAC17F958D2ee523a2206206994597C13D831ec7"}, P_INTEL)
try:
    agent.query_node(NODE, {"type": "security_intel", "network": "eth",
                            "address": "0xdAC17F958D2ee523a2206206994597C13D831ec7"}, P_INTEL)
    print("TEST4 budget guard: FAIL (spent past budget!)")
except BudgetExceeded:
    print("TEST4 budget guard tripped before overspend: PASS")

# 5. on-chain dispute: fake provider signs receipt for hash X but "delivers" hash Y
fake_provider = Account.from_key("0x" + secrets.token_hex(32))
promised = bytes.fromhex("11" * 32)
actual = bytes.fromhex("22" * 32)
msg = encode_defunct(receipt_message(agent.channel_id, 99, promised))
rsig = fake_provider.sign_message(msg).signature.hex()
dtx = file_dispute(agent.channels, CHAINS["qumtam"]["dispute"], agent.channel_id,
                   fake_provider.address, 99, promised, actual, rsig)
dc = w3.eth.contract(address=CHAINS["qumtam"]["dispute"], abi=DISPUTE_ABI).functions.disputeCount().call()
print(f"TEST5 dispute filed on-chain: tx={dtx} disputeCount={dc} -> {'PASS' if dc >= 1 else 'FAIL'}")

# 6. negative: matching hashes must revert
try:
    file_dispute(agent.channels, CHAINS["qumtam"]["dispute"], agent.channel_id,
                 fake_provider.address, 99, promised, promised, rsig)
    print("TEST6 no-mismatch dispute: FAIL (accepted!)")
except Exception:
    print("TEST6 no-mismatch dispute reverted: PASS")

print("ALL PRODUCT/GUARD/DISPUTE TESTS DONE")
