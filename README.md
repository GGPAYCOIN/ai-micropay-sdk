# ai-micropay-sdk

Autonomous pay-per-query data purchasing for AI agents on **GGCHAIN** and **Qumtam Chain**.

One on-chain transaction locks a budget in a payment channel; after that every query is a
**millisecond, zero-gas, EIP-712 signed off-chain voucher**. The provider settles the *last*
voucher on-chain and receives the whole amount at once; unused deposit is refunded automatically.

## Live deployment

| | GGCHAIN | Qumtam Chain |
|---|---|---|
| Chain ID | 2121217 | 424242 |
| MicropayChannel | `0xD839650Fc67ff1B94252928E6D24Ef5F9E974B95` | `0xadA2Dc73d409845a5c726695d7514B1f91eBA108` |
| Payment | native GG or any ERC20 (bUSDT `0xE77F05…b4aB`) | native QTM |

**Live data node** (sells Qumtam Shield security intel): `https://qumtamchain.com/api/datanode/info`

## Quick start

```python
from micropay import AutonomousDataAgent
import requests

info = requests.get("https://qumtamchain.com/api/datanode/info").json()
price = int(info["price_wei"]["qumtam"])   # 0.001 QTM per query

agent = AutonomousDataAgent("0xAGENT_PRIVATE_KEY", chain="qumtam",
                            daily_budget_wei=price * 100)   # budget circuit breaker

# ONE on-chain tx locks budget for 50 queries
agent.open_channel(info["provider_address"], deposit_wei=price * 50, ttl_seconds=86400)

# every query after this: ~150ms, zero gas, off-chain EIP-712 voucher
data = agent.query_node("https://qumtamchain.com/api/datanode",
                        {"type": "security_intel", "network": "eth",
                         "address": "0xdAC17F958D2ee523a2206206994597C13D831ec7"},
                        price)
print(data["score"], data["grade"])   # authenticity auto-verified against provider-signed receipt
```

ERC20 channel (e.g. bUSDT on GGCHAIN): `agent.open_channel(provider, amount, token="0xE77F05C01dac30901De8346c23242C4284dCb4aB")`

## LangChain

```python
from micropay.langchain_tool import make_intel_tool
tool = make_intel_tool(agent, "https://qumtamchain.com/api/datanode", price)
# add `tool` to any LangChain agent — it now buys live security intel autonomously
```

## Security model

- **chainId in EIP-712 domain** → vouchers cannot be replayed across chains.
- **channelId comes from the on-chain `ChannelOpened` event**, never computed client-side.
- **Monotonic `cumulativeAmount` + nonce** → provider only ever needs the latest voucher; stale/duplicate vouchers rejected.
- **`refundExpired()`** → payer reclaims full deposit if the provider disappears (no locked funds).
- **Signed delivery receipts** → provider signs `keccak(channelId ‖ nonce ‖ dataHash)` for every response; the SDK verifies hash + signature before accepting data and raises `DataIntegrityError` on mismatch (disputable evidence).
- **Budget circuit breaker** → `daily_budget_wei` hard-stops runaway agent loops.

## Layout

```
contracts/MicropayChannel.sol   # payment channel (native + ERC20), EIP-712 close
micropay/wallet.py              # EIP-712 voucher signer / recovery
micropay/channel.py             # open / close / refund on-chain
micropay/verifier.py            # data hash + signed receipt verification
micropay/agent.py               # AutonomousDataAgent (budget guard, query flow)
micropay/langchain_tool.py      # LangChain @tool adapter
provider/node.py                # reference data node (Shield intel, voucher ledger, settlement)
examples/e2e_demo.py            # full E2E: fund → open → 3 paid queries → settle
examples/erc20_test.py          # ERC20-channel E2E
```

E2E verified on both chains (native QTM, native GG, ERC20) — settlement txs on the respective explorers.
