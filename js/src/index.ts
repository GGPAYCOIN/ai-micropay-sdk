import { createHash } from "node:crypto";
import { Contract, Wallet, JsonRpcProvider, keccak256, concat, zeroPadValue, toBeHex, getBytes, verifyMessage, Signature } from "ethers";

export const CHAINS: Record<string, any> = {
  gg: {
    name: "GGCHAIN", chainId: 2121217, rpc: "https://rpc.gghyper.net",
    contract: "0xD839650Fc67ff1B94252928E6D24Ef5F9E974B95",
    dispute: "0x4aFeC06750A66Dde15Bf19Bd8fE13156F4165c17",
    nativeSymbol: "GG",
    tokens: { bUSDT: { address: "0xE77F05C01dac30901De8346c23242C4284dCb4aB", decimals: 18 } },
  },
  qumtam: {
    name: "Qumtam Chain", chainId: 424242, rpc: "https://rpc.qumtamchain.com",
    contract: "0xadA2Dc73d409845a5c726695d7514B1f91eBA108",
    dispute: "0xC28e8DA1a376Fcc04e3CF432b03d93355fFbc622",
    nativeSymbol: "QTM", tokens: {},
  },
};

const CHANNEL_ABI = [
  "function openChannel(address provider, uint64 expiry) payable returns (bytes32)",
  "function openChannelERC20(address provider, address token, uint256 amount, uint64 expiry) returns (bytes32)",
  "function channels(bytes32) view returns (address payer, address provider, address token, uint128 deposit, uint64 expiry, bool open)",
  "function refundExpired(bytes32 id)",
  "event ChannelOpened(bytes32 indexed channelId, address indexed payer, address indexed provider, address token, uint256 deposit, uint64 expiry)",
];
const ERC20_ABI = ["function approve(address spender, uint256 amount) returns (bool)"];
const DISPUTE_ABI = [
  "function fileDispute(bytes32 channelId, address provider, uint256 nonce, bytes32 promisedHash, bytes32 actualHash, uint8 v, bytes32 r, bytes32 s)",
];

function canonicalJson(x: any): string {
  if (Array.isArray(x)) return "[" + x.map(canonicalJson).join(",") + "]";
  if (x !== null && typeof x === "object")
    return "{" + Object.keys(x).sort().map((k) => JSON.stringify(k) + ":" + canonicalJson(x[k])).join(",") + "}";
  return JSON.stringify(x);
}

export function dataHash(data: any): string {
  return createHash("sha256").update(canonicalJson(data)).digest("hex");
}

export function receiptMessage(channelIdHex: string, nonce: number, dataHashHex: string): string {
  return keccak256(concat(["0x" + channelIdHex.replace(/^0x/, ""),
                           zeroPadValue(toBeHex(nonce), 32),
                           "0x" + dataHashHex.replace(/^0x/, "")]));
}

export function verifyDelivery(data: any, expectedHashHex: string, receiptSignature: string,
                               providerAddress: string, channelIdHex: string, nonce: number): boolean {
  const dh = dataHash(data);
  if (dh !== expectedHashHex.replace(/^0x/, "")) return false;
  const msg = getBytes(receiptMessage(channelIdHex, nonce, dh));
  const sig = receiptSignature.startsWith("0x") ? receiptSignature : "0x" + receiptSignature;
  return verifyMessage(msg, sig).toLowerCase() === providerAddress.toLowerCase();
}

export class BudgetExceeded extends Error {}
export class DataIntegrityError extends Error {}

export class MicropayAgent {
  cfg: any;
  chain: string;
  wallet: Wallet;
  channel: Contract;
  channelId: string | null = null;
  providerAddress: string | null = null;
  nonce = 0;
  cumulative = 0n;
  dailyBudgetWei: bigint | null;
  private day: string;
  private spentToday = 0n;

  constructor(privateKey: string, chain = "gg", dailyBudgetWei: bigint | null = null) {
    this.chain = chain;
    this.cfg = CHAINS[chain];
    this.wallet = new Wallet(privateKey, new JsonRpcProvider(this.cfg.rpc));
    this.channel = new Contract(this.cfg.contract, CHANNEL_ABI, this.wallet);
    this.dailyBudgetWei = dailyBudgetWei;
    this.day = new Date().toISOString().slice(0, 10);
  }

  get address(): string { return this.wallet.address; }

  async openChannel(providerAddr: string, depositWei: bigint, ttlSeconds = 86400, token?: string): Promise<string> {
    const expiry = Math.floor(Date.now() / 1000) + ttlSeconds;
    let rec;
    if (token) {
      const t = new Contract(token, ERC20_ABI, this.wallet);
      await (await t.approve(this.cfg.contract, depositWei)).wait();
      rec = await (await this.channel.openChannelERC20(providerAddr, token, depositWei, expiry)).wait();
    } else {
      rec = await (await this.channel.openChannel(providerAddr, expiry, { value: depositWei })).wait();
    }
    const ev = rec!.logs.map((l: any) => { try { return this.channel.interface.parseLog(l); } catch { return null; } })
      .find((p: any) => p && p.name === "ChannelOpened");
    if (!ev) throw new Error("ChannelOpened event not found");
    this.channelId = ev.args.channelId;
    this.providerAddress = providerAddr;
    this.nonce = 0;
    this.cumulative = 0n;
    return rec!.hash;
  }

  async signVoucher(cumulativeAmount: bigint, nonce: number, dataHashHex: string): Promise<string> {
    return this.wallet.signTypedData(
      { name: "DataMicropayEngine", version: "1", chainId: this.cfg.chainId, verifyingContract: this.cfg.contract },
      { MicroVoucher: [
          { name: "channelId", type: "bytes32" }, { name: "cumulativeAmount", type: "uint256" },
          { name: "nonce", type: "uint256" }, { name: "dataHash", type: "bytes32" }] },
      { channelId: this.channelId, cumulativeAmount, nonce, dataHash: "0x" + dataHashHex.replace(/^0x/, "") });
  }

  private budgetGuard(amount: bigint) {
    const today = new Date().toISOString().slice(0, 10);
    if (today !== this.day) { this.day = today; this.spentToday = 0n; }
    if (this.dailyBudgetWei !== null && this.spentToday + amount > this.dailyBudgetWei)
      throw new BudgetExceeded(`daily budget ${this.dailyBudgetWei} wei would be exceeded`);
    this.spentToday += amount;
  }

  async queryNode(endpointUrl: string, query: any, priceWei: bigint): Promise<any> {
    if (!this.channelId) throw new Error("openChannel() first");
    this.budgetGuard(priceWei);
    const qhash = createHash("sha256").update(canonicalJson(query)).digest("hex");
    this.nonce += 1;
    this.cumulative += priceWei;
    const signature = await this.signVoucher(this.cumulative, this.nonce, qhash);
    const res = await fetch(`${endpointUrl.replace(/\/$/, "")}/get-data`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chain: this.chain, query, channel_id: this.channelId.replace(/^0x/, ""),
                             cumulative_amount: this.cumulative.toString(), nonce: this.nonce,
                             query_hash: qhash, signature }),
    });
    const body: any = await res.json();
    if (!res.ok || !body.ok) {
      this.nonce -= 1; this.cumulative -= priceWei; this.spentToday -= priceWei;
      throw new Error(`query failed: ${body.error ?? res.status}`);
    }
    if (!verifyDelivery(body.data, body.data_hash, body.receipt_signature,
                        body.provider_address, this.channelId, this.nonce)) {
      let dtx: string | null = null;
      try { dtx = await this.fileDispute(body.data, body.data_hash, body.receipt_signature); } catch {}
      throw new DataIntegrityError("provider data does not match its signed receipt — session terminated"
        + (dtx ? `; on-chain dispute filed: ${dtx}` : ""));
    }
    return body.data;
  }

  async fileDispute(data: any, promisedHashHex: string, receiptSignature: string): Promise<string> {
    const d = new Contract(this.cfg.dispute, DISPUTE_ABI, this.wallet);
    const sig = Signature.from(receiptSignature.startsWith("0x") ? receiptSignature : "0x" + receiptSignature);
    const rec = await (await d.fileDispute(this.channelId, this.providerAddress, this.nonce,
      "0x" + promisedHashHex.replace(/^0x/, ""), "0x" + dataHash(data), sig.v, sig.r, sig.s)).wait();
    if (rec!.status !== 1) throw new Error("dispute tx reverted");
    return rec!.hash;
  }

  async refundExpired(): Promise<string> {
    const rec = await (await this.channel.refundExpired(this.channelId)).wait();
    if (rec!.status !== 1) throw new Error("refund tx reverted");
    return rec!.hash;
  }
}
