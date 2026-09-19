#!/usr/bin/env python3
"""Verify MicropayChannel + DisputeRegistry source on both Blockscout explorers."""
import json
import sys
import time

import requests

MC = open("/opt/ai-datanode/contracts/MicropayChannel.sol").read()
DR = open("/opt/ai-datanode/contracts/DisputeRegistry.sol").read()
C = json.load(open("/opt/ai-datanode/contracts.json"))
D = json.load(open("/opt/ai-datanode/disputes.json"))

TARGETS = [
    ("https://explorer.gghyper.net", C["gg"], "MicropayChannel", MC),
    ("https://explorer.qumtamchain.com", C["qumtam"], "MicropayChannel", MC),
    ("https://explorer.gghyper.net", D["gg"], "DisputeRegistry", DR),
    ("https://explorer.qumtamchain.com", D["qumtam"], "DisputeRegistry", DR),
]

for base, addr, name, src in TARGETS:
    st = requests.get(f"{base}/api/v2/smart-contracts/{addr}", timeout=20).json()
    if st.get("is_verified"):
        print(f"[{base.split('.')[1]}] {name} {addr[:10]}… already verified")
        continue
    r = requests.post(f"{base}/api/v2/smart-contracts/{addr}/verification/via/flattened-code",
                      json={"compiler_version": "v0.8.20+commit.a1b79de6",
                            "license_type": "mit",
                            "source_code": src,
                            "is_optimization_enabled": False,
                            "evm_version": "paris",
                            "autodetect_constructor_args": True},
                      timeout=30)
    print(f"[{base.split('.')[1]}] {name} {addr[:10]}… submit: {r.status_code} {r.text[:80]}")

print("waiting 45s for verification workers…")
time.sleep(45)
ok = 0
for base, addr, name, _ in TARGETS:
    st = requests.get(f"{base}/api/v2/smart-contracts/{addr}", timeout=20).json()
    v = st.get("is_verified", False)
    ok += bool(v)
    print(f"[{base.split('.')[1]}] {name} {addr[:12]}… verified: {v}")
print(f"{ok}/4 verified")
sys.exit(0 if ok == 4 else 1)
