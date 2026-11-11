/* Independent Node.js sample. No Python imports and no agent-framework dependency. */
const { generateKeyPairSync, sign } = require("node:crypto");
const readline = require("node:readline");

function canonical(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  return "{" + Object.keys(value).sort().map((key) =>
    JSON.stringify(key) + ":" + canonical(value[key])).join(",") + "}";
}

async function main() {
  const keys = generateKeyPairSync("ed25519");
  console.log(JSON.stringify({ public_key: keys.publicKey.export({ format: "jwk" }).x }));
  const input = readline.createInterface({ input: process.stdin, terminal: false });
  for await (const line of input) {
    const { url, scope, capability, kind } = JSON.parse(line);
    const parsed = new URL(url);
    if (parsed.origin !== `http://127.0.0.1:${parsed.port}` ||
        parsed.pathname !== "/v1/protected-action" || parsed.search || parsed.hash ||
        parsed.username || parsed.password) throw new Error("Loopback Trust endpoint required");
    const [payload, issuerSignature] = capability.split(".");
    const jti = JSON.parse(Buffer.from(payload, "base64url")).jti;
    const action = { ...scope, body: { data: [{ text: "Synthetic external notice" }] } };
    if (kind === "destination") action.endpoint_id = "UNAUTHORIZED";
    const message = Buffer.from(canonical({ action, jti, ts: Math.floor(Date.now() / 1000) }));
    const signature = sign(null, message, keys.privateKey).toString("base64url");
    const proof = message.toString("base64url") + "." + signature;
    if (kind === "altered") action.body.data[0].text = "Modified synthetic notice";
    const badSignature = (issuerSignature[0] === "A" ? "B" : "A") + issuerSignature.slice(1);
    const token = kind === "invalid" ? payload + "." + badSignature : capability;
    const response = await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, capability: token, proof }),
      redirect: "error", signal: AbortSignal.timeout(10000),
    });
    console.log(JSON.stringify({ status: response.status, result: await response.json() }));
  }
}
main().catch(() => { process.exitCode = 1; });
