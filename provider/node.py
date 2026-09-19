#!/usr/bin/env python3
"""AI Data Node — sells Qumtam Shield security intel pay-per-query via off-chain micro-vouchers."""
import json
import os
import threading
import time

import requests
from fastapi import FastAPI
from pydantic import BaseModel
from web3 import Web3

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from micropay.chains import CHAINS
from micropay.verifier import data_hash, sign_receipt
from micropay.wallet import recover_voucher_signer

app = FastAPI(title="AI Data Node — Qumtam Shield intel")

BASE = os.environ.get("DATANODE_DIR", "/opt/ai-datanode")
PROVIDER_KEY = open(os.environ.get("DATANODE_KEY", "/opt/ggstack-demo/sequencer.key")).read().strip()
SHIELD_URL = os.environ.get("SHIELD_URL", "http://127.0.0.1:8096")
PRICE_WEI = {"gg": int(os.environ.get("PRICE_GG", str(10**15))),
             "qumtam": int(os.environ.get("PRICE_QTM", str(10**15)))}
PRODUCTS = {"security_intel": 1, "wallet_risk": 5, "chain_health": 3}
SHIELD_KEY = os.environ.get("DATANODE_SHIELD_KEY", "")
CH_CACHE = {}
VOUCHER_FILE = f"{BASE}/vouchers.json"
CONTRACTS = json.load(open(f"{BASE}/contracts.json")) if os.path.exists(f"{BASE}/contracts.json") else {}
DISPUTES = json.load(open(f"{BASE}/disputes.json")) if os.path.exists(f"{BASE}/disputes.json") else {}
ABI = json.load(open(f"{BASE}/abi.json")) if os.path.exists(f"{BASE}/abi.json") else []
ADMIN_KEY = os.environ.get("DATANODE_ADMIN_KEY", "")
SETTLE_INTERVAL = int(os.environ.get("DATANODE_SETTLE_INTERVAL", "600"))
SETTLE_BUFFER = int(os.environ.get("DATANODE_SETTLE_BUFFER", "7200"))
LOCK = threading.Lock()

from eth_account import Account
PROVIDER_ADDRESS = Account.from_key(PROVIDER_KEY).address

W3 = {c: Web3(Web3.HTTPProvider(("http://127.0.0.1:8547" if c == "qumtam" else CHAINS[c]["rpc"]),
                                request_kwargs={"timeout": 20})) for c in CONTRACTS}


def load_vouchers():
    try:
        return json.load(open(VOUCHER_FILE))
    except Exception:
        return {}


def save_vouchers(v):
    tmp = VOUCHER_FILE + ".tmp"
    json.dump(v, open(tmp, "w"))
    os.replace(tmp, VOUCHER_FILE)


def get_channel(chain, channel_id: bytes):
    w3 = W3[chain]
    c = w3.eth.contract(address=Web3.to_checksum_address(CONTRACTS[chain]), abi=ABI)
    payer, provider, token, deposit, expiry, is_open = c.functions.channels(channel_id).call()
    return {"payer": payer, "provider": provider, "token": token, "deposit": deposit,
            "expiry": expiry, "open": is_open}


def shield_intel(network: str, address: str) -> dict:
    """Security intel product: latest Shield audit data for an address."""
    out = {"network": network, "address": address.lower(), "source": "Qumtam Shield", "ts": int(time.time())}
    try:
        r = requests.get(f"{SHIELD_URL}/api/shield/project/{network}/{address}", timeout=15).json()
        if r.get("ok"):
            p = r["project"]
            out.update({"found": True, "name": p.get("name"), "score": p.get("score"),
                        "grade": p.get("grade"), "type": p.get("type"), "audited_ts": p.get("ts"),
                        "anchor_tx": p.get("anchor_tx"),
                        "history": [{"score": h["score"], "grade": h["grade"], "ts": h["ts"]} for h in r.get("history", [])[:8]],
                        "report_url": f"https://qumtamchain.com/p/{network}/{address.lower()}"})
            return out
    except Exception:
        pass
    out.update({"found": False,
                "note": "No Shield audit report exists yet for this address — run one free at https://qumtamchain.com/audit.html"})
    return out


def wallet_risk(network: str, address: str) -> dict:
    """Premium product: LIVE wallet fraud scan (fresh, not cached)."""
    out = {"network": network, "address": address.lower(), "source": "Qumtam Shield live scan", "ts": int(time.time())}
    try:
        r = requests.post(f"{SHIELD_URL}/api/shield/scan", json={"network": network, "address": address},
                          headers={"x-shield-key": SHIELD_KEY}, timeout=60).json()
        if r.get("ok"):
            out.update({"found": True, "risk_score": r.get("risk_score"), "risk_level": r.get("risk_level"),
                        "type": r.get("type"), "balance": r.get("balance"), "tx_count": r.get("tx_count"),
                        "tokens_held": len(r.get("tokens") or []), "approvals": r.get("approvals"),
                        "flags": [{"severity": f["severity"], "message": f["message"]} for f in (r.get("flags") or [])[:12]],
                        "report_id": r.get("report_id"), "anchor_tx": r.get("anchor_tx")})
            return out
        out.update({"found": False, "error": r.get("error", "scan failed")})
    except Exception:
        out.update({"found": False, "error": "scan unavailable"})
    return out


def chain_health(network: str) -> dict:
    """Premium product: full chain-health audit (cached 6h per network)."""
    now = time.time()
    if network in CH_CACHE and now - CH_CACHE[network][0] < 21600:
        d = dict(CH_CACHE[network][1])
        d["cached"] = True
        return d
    out = {"network": network, "source": "Qumtam Shield chain audit", "ts": int(now)}
    try:
        r = requests.post(f"{SHIELD_URL}/api/shield/chainaudit",
                          json={"network": network, "address": "0x" + "0" * 40},
                          headers={"x-shield-key": SHIELD_KEY}, timeout=90).json()
        if r.get("ok"):
            out.update({"found": True, "score": r.get("score"), "grade": r.get("grade"),
                        "chain_id": r.get("chain_id"), "block_time": r.get("block_time"),
                        "producers": r.get("producers"), "peers": r.get("peers"),
                        "findings": [{"severity": f["severity"], "message": f["message"]} for f in (r.get("findings") or [])[:12]],
                        "report_id": r.get("report_id")})
            CH_CACHE[network] = (now, dict(out))
            return out
        out.update({"found": False, "error": r.get("error", "chain audit failed")})
    except Exception:
        out.update({"found": False, "error": "chain audit unavailable"})
    return out


class DataReq(BaseModel):
    chain: str
    query: dict
    channel_id: str
    cumulative_amount: str
    nonce: int
    query_hash: str
    signature: str


@app.get("/api/datanode/info")
def info():
    return {"ok": True, "provider_address": PROVIDER_ADDRESS, "contracts": CONTRACTS,
            "price_wei": {k: str(v) for k, v in PRICE_WEI.items()},
            "products": {p: {c: str(PRICE_WEI[c] * m) for c in PRICE_WEI} for p, m in PRODUCTS.items()},
            "product_docs": {
                "security_intel": "Latest anchored audit score/grade/history for a contract or wallet — {type,network,address}",
                "wallet_risk": "LIVE wallet fraud scan: risk score, flags, approvals, scam interactions — {type,network,address}",
                "chain_health": "Full chain audit: liveness, producers, block time, RPC risk surface — {type,network}"},
            "dispute_registry": DISPUTES,
            "chains": {k: CHAINS[k]["name"] for k in CONTRACTS}}


@app.post("/api/datanode/get-data")
def get_data(req: DataReq):
    chain = req.chain
    if chain not in CONTRACTS:
        return {"ok": False, "error": f"unsupported chain '{chain}'"}
    try:
        channel_id = bytes.fromhex(req.channel_id.removeprefix("0x"))
        cumulative = int(req.cumulative_amount)
        qhash = bytes.fromhex(req.query_hash.removeprefix("0x"))
        assert len(channel_id) == 32 and len(qhash) == 32 and cumulative > 0 and req.nonce > 0
    except Exception:
        return {"ok": False, "error": "malformed payload"}

    signer = recover_voucher_signer(CHAINS[chain]["chain_id"], CONTRACTS[chain],
                                    channel_id, cumulative, req.nonce, qhash, req.signature)
    try:
        ch = get_channel(chain, channel_id)
    except Exception:
        return {"ok": False, "error": "channel lookup failed"}
    if not ch["open"]:
        return {"ok": False, "error": "channel is closed"}
    if ch["payer"].lower() != signer.lower():
        return {"ok": False, "error": "voucher signer is not the channel payer"}
    if ch["provider"].lower() != PROVIDER_ADDRESS.lower():
        return {"ok": False, "error": "channel provider is not this node"}
    if ch["expiry"] < time.time():
        return {"ok": False, "error": "channel expired"}
    if cumulative > ch["deposit"]:
        return {"ok": False, "error": "voucher exceeds channel deposit — open a bigger channel"}

    q = req.query
    ptype = q.get("type")
    if ptype not in PRODUCTS:
        return {"ok": False, "error": f"unknown product — choose one of {list(PRODUCTS)}"}
    if ptype in ("security_intel", "wallet_risk") and not (q.get("network") and q.get("address")):
        return {"ok": False, "error": "network and address are required"}
    if ptype == "chain_health" and not q.get("network"):
        return {"ok": False, "error": "network is required"}

    price = PRICE_WEI[chain] * PRODUCTS[ptype]
    with LOCK:
        vs = load_vouchers()
        prev = vs.get(req.channel_id, {"cumulative": 0, "nonce": 0})
        if req.nonce <= prev["nonce"]:
            return {"ok": False, "error": "stale nonce"}
        if cumulative - prev["cumulative"] < price:
            return {"ok": False, "error": f"underpaid: {ptype} costs {price} wei per query"}
        vs[req.channel_id] = {"chain": chain, "cumulative": cumulative, "nonce": req.nonce,
                              "query_hash": req.query_hash, "signature": req.signature,
                              "payer": ch["payer"], "ts": int(time.time())}
        save_vouchers(vs)

    if ptype == "wallet_risk":
        data = wallet_risk(q["network"], q["address"])
    elif ptype == "chain_health":
        data = chain_health(q["network"])
    else:
        data = shield_intel(q["network"], q["address"])
    dhash = data_hash(data)
    receipt = sign_receipt(PROVIDER_KEY, channel_id, req.nonce, dhash)
    return {"ok": True, "data": data, "data_hash": dhash.hex(),
            "receipt_signature": receipt, "provider_address": PROVIDER_ADDRESS,
            "paid_total_wei": str(cumulative), "queries_served": req.nonce}


class SettleReq(BaseModel):
    chain: str
    channel_id: str
    admin_key: str


def settle_channel(chain: str, channel_id_hex: str) -> dict:
    vs = load_vouchers()
    v = vs.get(channel_id_hex)
    if not v or v["chain"] != chain:
        return {"ok": False, "error": "no voucher stored for this channel"}
    if v.get("settled"):
        return {"ok": False, "error": "already settled", "tx": v["settled"].get("tx")}
    w3 = W3[chain]
    acct = w3.eth.account.from_key(PROVIDER_KEY)
    c = w3.eth.contract(address=Web3.to_checksum_address(CONTRACTS[chain]), abi=ABI)
    sig = bytes.fromhex(v["signature"].removeprefix("0x"))
    r, s, vv = sig[:32], sig[32:64], sig[64]
    if vv < 27:
        vv += 27
    tx = c.functions.close(bytes.fromhex(channel_id_hex.removeprefix("0x")), int(v["cumulative"]), int(v["nonce"]),
                           bytes.fromhex(v["query_hash"].removeprefix("0x")), vv, r, s).build_transaction({
        "from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address, "pending"),
        "gas": 300000, "gasPrice": max(w3.eth.gas_price, w3.to_wei(1, "gwei")),
        "chainId": CHAINS[chain]["chain_id"]})
    signed = acct.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    rec = w3.eth.wait_for_transaction_receipt(h, timeout=120)
    txh = rec["transactionHash"].hex()
    if rec["status"] == 1:
        with LOCK:
            vs = load_vouchers()
            if channel_id_hex in vs:
                vs[channel_id_hex]["settled"] = {"tx": txh, "ts": int(time.time())}
                save_vouchers(vs)
    return {"ok": rec["status"] == 1, "tx": txh, "settled_wei": v["cumulative"], "queries": v["nonce"]}


def _mark_settled(channel_id_hex: str, tx: str):
    with LOCK:
        vs = load_vouchers()
        if channel_id_hex in vs and not vs[channel_id_hex].get("settled"):
            vs[channel_id_hex]["settled"] = {"tx": tx, "ts": int(time.time())}
            save_vouchers(vs)


def settlement_loop():
    """Auto-settle: close any channel nearing expiry or with fully-spent deposit."""
    while True:
        time.sleep(SETTLE_INTERVAL)
        try:
            now = time.time()
            for cid, v in list(load_vouchers().items()):
                if v.get("settled"):
                    continue
                try:
                    ch = get_channel(v["chain"], bytes.fromhex(cid))
                except Exception:
                    continue
                if not ch["open"]:
                    _mark_settled(cid, "closed-externally")
                    continue
                if (ch["expiry"] - now) < SETTLE_BUFFER or int(v["cumulative"]) >= ch["deposit"]:
                    try:
                        r = settle_channel(v["chain"], cid)
                        print(f"[settle-bot] {v['chain']} {cid[:12]}… -> {r}", flush=True)
                    except Exception as e:
                        print(f"[settle-bot] {cid[:12]}… failed: {e}", flush=True)
        except Exception:
            pass


threading.Thread(target=settlement_loop, daemon=True).start()


@app.get("/api/datanode/stats")
def node_stats():
    vs = load_vouchers()
    per = {}
    for _cid, v in vs.items():
        p = per.setdefault(v["chain"], {"channels": 0, "queries": 0, "earned_wei": 0, "pending_wei": 0, "settled": 0})
        p["channels"] += 1
        p["queries"] += int(v["nonce"])
        st = v.get("settled")
        if st and st.get("tx") not in (None, "closed-externally"):
            p["earned_wei"] += int(v["cumulative"])
            p["settled"] += 1
        elif not st:
            p["pending_wei"] += int(v["cumulative"])
    return {"ok": True, "provider_address": PROVIDER_ADDRESS, "contracts": CONTRACTS,
            "price_wei": {k: str(x) for k, x in PRICE_WEI.items()},
            "auto_settle": {"interval_sec": SETTLE_INTERVAL, "expiry_buffer_sec": SETTLE_BUFFER},
            "chains": {k: {"channels": p["channels"], "queries": p["queries"], "settled": p["settled"],
                           "earned_wei": str(p["earned_wei"]), "pending_wei": str(p["pending_wei"])}
                       for k, p in per.items()}}


@app.post("/api/datanode/settle")
def settle(req: SettleReq):
    if not ADMIN_KEY or req.admin_key != ADMIN_KEY:
        return {"ok": False, "error": "forbidden"}
    return settle_channel(req.chain, req.channel_id)
