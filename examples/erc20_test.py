#!/usr/bin/env python3
"""ERC20-channel path test on GGCHAIN with a throwaway test token."""
import json
import os
import secrets
import sys

sys.path.insert(0, "/opt/ai-datanode")
import solcx
from web3 import Web3

from micropay import AutonomousDataAgent, CHAINS
import requests

TOKEN_SRC = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;
contract TestToken {
    string public name = "MicropayTest"; string public symbol = "MPT"; uint8 public decimals = 18;
    mapping(address=>uint256) public balanceOf; mapping(address=>mapping(address=>uint256)) public allowance;
    constructor(){ balanceOf[msg.sender] = 1000 ether; }
    function transfer(address to,uint256 a) external returns(bool){ balanceOf[msg.sender]-=a; balanceOf[to]+=a; return true; }
    function approve(address s,uint256 a) external returns(bool){ allowance[msg.sender][s]=a; return true; }
    function transferFrom(address f,address t,uint256 a) external returns(bool){ allowance[f][msg.sender]-=a; balanceOf[f]-=a; balanceOf[t]+=a; return true; }
}
"""

RPC = "https://rpc.gghyper.net"
NODE = "https://qumtamchain.com/api/datanode"
FUNDER_KEY = open("/opt/ggstack-demo/sequencer.key").read().strip()
CONTRACTS = json.load(open("/opt/ai-datanode/contracts.json"))
CHAINS["gg"]["contract"] = CONTRACTS["gg"]

solcx.set_solc_version("0.8.20")
out = solcx.compile_source(TOKEN_SRC, output_values=["abi", "bin"], evm_version="paris")
cid = next(k for k in out if k.endswith(":TestToken"))
abi, bytecode = out[cid]["abi"], out[cid]["bin"]

w3 = Web3(Web3.HTTPProvider(RPC))
funder = w3.eth.account.from_key(FUNDER_KEY)

def send(acct, tx):
    tx.pop("maxFeePerGas", None)
    tx.pop("maxPriorityFeePerGas", None)
    tx.update({"nonce": w3.eth.get_transaction_count(acct.address, "pending"),
               "gasPrice": max(w3.eth.gas_price, w3.to_wei(1, "gwei")), "chainId": 2121217})
    s = acct.sign_transaction(tx)
    return w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(s.raw_transaction), timeout=120)

# deploy test token (funder holds 1000 MPT)
c = w3.eth.contract(abi=abi, bytecode=bytecode)
rec = send(funder, c.constructor().build_transaction({"from": funder.address, "gas": 1200000}))
token_addr = rec["contractAddress"]
tok = w3.eth.contract(address=token_addr, abi=abi)
print("test token:", token_addr)

# agent wallet: fund gas + 1 MPT
agent_key = "0x" + secrets.token_hex(32)
agent_addr = w3.eth.account.from_key(agent_key).address
send(funder, {"to": agent_addr, "value": w3.to_wei("0.01", "ether"), "gas": 21000})
send(funder, tok.functions.transfer(agent_addr, w3.to_wei(1, "ether")).build_transaction({"from": funder.address, "gas": 100000}))
print("agent funded:", agent_addr)

info = requests.get(f"{NODE}/info", timeout=15).json()
PRICE = int(info["price_wei"]["gg"])
agent = AutonomousDataAgent(agent_key, chain="gg", daily_budget_wei=PRICE * 100)
txh = agent.open_channel(info["provider_address"], PRICE * 5, ttl_seconds=3600, token=token_addr)
print("ERC20 channel open tx", txh, "id", agent.channel_id.hex())

d = agent.query_node(NODE, {"type": "security_intel", "network": "qumtam", "address": "0xC8e3aeb0C8B30f1606a5a4852B4a782546C05C1A"}, PRICE)
print("query ok — found:", d.get("found"), "score:", d.get("score"))

admin = open("/opt/ai-datanode/.admin_key").read().strip()
r = requests.post(f"{NODE}/settle", json={"chain": "gg", "channel_id": agent.channel_id.hex(), "admin_key": admin}, timeout=120).json()
prov_bal = w3.from_wei(tok.functions.balanceOf(funder.address).call(), "ether")
agent_bal = w3.from_wei(tok.functions.balanceOf(agent_addr).call(), "ether")
print(f"settle ok={r['ok']} tx={r.get('tx')} | provider MPT={prov_bal} agent MPT={agent_bal}")
print("ERC20 E2E COMPLETE" if r["ok"] else "ERC20 E2E FAILED")
