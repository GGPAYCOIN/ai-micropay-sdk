#!/usr/bin/env python3
"""Deploy DisputeRegistry to GGCHAIN + Qumtam."""
import json

import solcx
from web3 import Web3

SRC = open("/opt/ai-datanode/contracts/DisputeRegistry.sol").read()
KEY = open("/opt/ggstack-demo/sequencer.key").read().strip()
TARGETS = {"gg": {"rpc": "https://rpc.gghyper.net", "chain_id": 2121217},
           "qumtam": {"rpc": "http://127.0.0.1:8547", "chain_id": 424242}}

solcx.set_solc_version("0.8.20")
out = solcx.compile_source(SRC, output_values=["abi", "bin"], evm_version="paris")
cid = next(k for k in out if k.endswith(":DisputeRegistry"))
abi, bytecode = out[cid]["abi"], out[cid]["bin"]
json.dump(abi, open("/opt/ai-datanode/dispute_abi.json", "w"))

results = {}
for name, t in TARGETS.items():
    w3 = Web3(Web3.HTTPProvider(t["rpc"], request_kwargs={"timeout": 30}))
    acct = w3.eth.account.from_key(KEY)
    c = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx = c.constructor().build_transaction({
        "from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address, "pending"),
        "gas": 1000000, "gasPrice": max(w3.eth.gas_price, w3.to_wei(1, "gwei")), "chainId": t["chain_id"]})
    rec = w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(acct.sign_transaction(tx).raw_transaction), timeout=180)
    assert rec["status"] == 1, name
    results[name] = rec["contractAddress"]
    print(f"[{name}] DisputeRegistry at {rec['contractAddress']}")

json.dump(results, open("/opt/ai-datanode/disputes.json", "w"))
print("DONE", json.dumps(results))
