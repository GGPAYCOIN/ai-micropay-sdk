#!/usr/bin/env python3
"""Compile MicropayChannel.sol (solc 0.8.20, EVM paris) and deploy to GGCHAIN + Qumtam."""
import json
import sys

import solcx
from web3 import Web3

SRC = open("/opt/ai-datanode/MicropayChannel.sol").read()
KEY = open("/opt/ggstack-demo/sequencer.key").read().strip()

TARGETS = {
    "gg": {"rpc": "https://rpc.gghyper.net", "chain_id": 2121217},
    "qumtam": {"rpc": "http://127.0.0.1:8547", "chain_id": 424242},
}

try:
    solcx.set_solc_version("0.8.20")
except Exception:
    solcx.install_solc("0.8.20")
    solcx.set_solc_version("0.8.20")

out = solcx.compile_source(SRC, output_values=["abi", "bin"], evm_version="paris")
cid = next(k for k in out if k.endswith(":MicropayChannel"))
abi, bytecode = out[cid]["abi"], out[cid]["bin"]
json.dump(abi, open("/opt/ai-datanode/abi.json", "w"))
print("compiled, bytecode bytes:", len(bytecode) // 2)

results = {}
for name, t in TARGETS.items():
    w3 = Web3(Web3.HTTPProvider(t["rpc"], request_kwargs={"timeout": 30}))
    acct = w3.eth.account.from_key(KEY)
    print(f"[{name}] deployer {acct.address} balance {w3.from_wei(w3.eth.get_balance(acct.address), 'ether')}")
    c = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx = c.constructor().build_transaction({
        "from": acct.address,
        "nonce": w3.eth.get_transaction_count(acct.address, "pending"),
        "gas": 1500000,
        "gasPrice": max(w3.eth.gas_price, w3.to_wei(1, "gwei")),
        "chainId": t["chain_id"],
    })
    signed = acct.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    rec = w3.eth.wait_for_transaction_receipt(h, timeout=180)
    if rec["status"] != 1:
        print(f"[{name}] DEPLOY FAILED"); sys.exit(1)
    results[name] = rec["contractAddress"]
    print(f"[{name}] MicropayChannel deployed at {rec['contractAddress']}")

json.dump(results, open("/opt/ai-datanode/contracts.json", "w"))
print("DONE", json.dumps(results))
