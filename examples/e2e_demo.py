#!/usr/bin/env python3
"""E2E: fresh agent wallet -> open channel -> 3 paid queries -> provider settles on-chain."""
import json
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests
from web3 import Web3

from micropay import AutonomousDataAgent, CHAINS

CHAIN = sys.argv[1] if len(sys.argv) > 1 else "qumtam"
NODE = os.environ.get("NODE_URL", "https://qumtamchain.com/api/datanode")
FUNDER_KEY = open("/opt/ggstack-demo/sequencer.key").read().strip()
CONTRACTS = json.load(open("/opt/ai-datanode/contracts.json"))
CHAINS[CHAIN]["contract"] = CONTRACTS[CHAIN]
RPC = "http://127.0.0.1:8547" if CHAIN == "qumtam" else CHAINS[CHAIN]["rpc"]
CHAINS[CHAIN]["rpc"] = RPC

info = requests.get(f"{NODE}/info", timeout=15).json()
PROVIDER = info["provider_address"]
PRICE = int(info["price_wei"][CHAIN])
print(f"provider: {PROVIDER} | price/query: {PRICE} wei")

# 1. fresh agent wallet, funded by sequencer
agent_key = "0x" + secrets.token_hex(32)
w3 = Web3(Web3.HTTPProvider(RPC))
funder = w3.eth.account.from_key(FUNDER_KEY)
agent_addr = w3.eth.account.from_key(agent_key).address
fund = w3.to_wei("0.02", "ether")
tx = {"to": agent_addr, "value": fund, "gas": 21000,
      "gasPrice": max(w3.eth.gas_price, w3.to_wei(1, "gwei")),
      "nonce": w3.eth.get_transaction_count(funder.address, "pending"),
      "chainId": CHAINS[CHAIN]["chain_id"]}
signed = funder.sign_transaction(tx)
w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(signed.raw_transaction), timeout=120)
print(f"agent {agent_addr} funded with {w3.from_wei(fund, 'ether')} {CHAINS[CHAIN]['native_symbol']}")

# 2. open channel: lock budget for 10 queries
agent = AutonomousDataAgent(agent_key, chain=CHAIN, daily_budget_wei=PRICE * 100)
deposit = PRICE * 10
txh = agent.open_channel(PROVIDER, deposit, ttl_seconds=3600)
print(f"channel open tx {txh}\nchannel_id {agent.channel_id.hex()}")

# 3. three millisecond off-chain paid queries
import time
for q in [{"type": "security_intel", "network": "arbitrum", "address": "0x29B18833445aC9F43A24e7E65dB85CdC4CE0559c"},
          {"type": "security_intel", "network": "eth", "address": "0xdAC17F958D2ee523a2206206994597C13D831ec7"},
          {"type": "security_intel", "network": "gg", "address": "0x82b163784b0d0371417B0eDbDF71A5B15c47B444"}]:
    t0 = time.time()
    data = agent.query_node(NODE, q, PRICE)
    ms = round((time.time() - t0) * 1000)
    print(f"  query {agent.nonce}: {q['network']}/{q['address'][:10]}… -> found={data.get('found')} "
          f"score={data.get('score')} grade={data.get('grade')} [{ms}ms, integrity ✓]")

print(f"total spent off-chain: {agent.cumulative_amount} wei over {agent.nonce} vouchers")

# 4. provider settles the LAST voucher on-chain (gets everything at once)
admin_key = os.environ["DATANODE_ADMIN_KEY"]
r = requests.post(f"{NODE}/settle", json={"chain": CHAIN, "channel_id": agent.channel_id.hex(),
                                          "admin_key": admin_key}, timeout=120).json()
print(f"settlement: ok={r['ok']} tx={r.get('tx')} settled={r.get('settled_wei')} wei for {r.get('queries')} queries")

ch = agent.channels.get_channel(agent.channel_id)
print(f"channel now open={ch['open']} (refund of unused deposit sent back to agent)")
print("E2E COMPLETE" if r["ok"] and not ch["open"] else "E2E FAILED")
