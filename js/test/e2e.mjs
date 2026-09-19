import { readFileSync } from "node:fs";
import { MicropayAgent } from "../dist/index.js";

const NODE = "https://qumtamchain.com/api/datanode";
const key = readFileSync("/tmp/ts_agent.key", "utf8").trim();

const info = await (await fetch(`${NODE}/info`)).json();
const price = BigInt(info.products.security_intel.qumtam);
console.log("provider:", info.provider_address, "| price:", price.toString());

const agent = new MicropayAgent(key, "qumtam", price * 100n);
console.log("agent:", agent.address);

const tx = await agent.openChannel(info.provider_address, price * 10n, 3600);
console.log("channel open tx:", tx, "\nchannel:", agent.channelId);

for (const [net, addr] of [["eth", "0xdAC17F958D2ee523a2206206994597C13D831ec7"],
                           ["arbitrum", "0x29B18833445aC9F43A24e7E65dB85CdC4CE0559c"]]) {
  const t0 = Date.now();
  const d = await agent.queryNode(NODE, { type: "security_intel", network: net, address: addr }, price);
  console.log(`  query ${agent.nonce}: ${net} -> score=${d.score} grade=${d.grade} [${Date.now() - t0}ms, integrity ✓]`);
}

// budget guard test: tiny budget agent
const { BudgetExceeded } = await import("../dist/index.js");
const tiny = new MicropayAgent(key, "qumtam", price);
tiny.channelId = agent.channelId; tiny.providerAddress = info.provider_address;
tiny.nonce = agent.nonce; tiny.cumulative = agent.cumulative;
try {
  await tiny.queryNode(NODE, { type: "security_intel", network: "eth", address: "0xdAC17F958D2ee523a2206206994597C13D831ec7" }, price);
  await tiny.queryNode(NODE, { type: "security_intel", network: "eth", address: "0xdAC17F958D2ee523a2206206994597C13D831ec7" }, price);
  console.log("budget guard: FAIL");
} catch (e) {
  console.log(e instanceof BudgetExceeded ? "budget guard tripped: PASS" : `budget: unexpected ${e.message}`);
}

console.log(`spent off-chain: ${agent.cumulative + price} wei — auto-settlement bot will close the channel`);
console.log("TS E2E COMPLETE");
