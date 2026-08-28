/* Capture browser-only StockTool evidence through an existing Chrome CDP port.
 * No browser profile, proxy, product file, or user-data directory is changed.
 */
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { basename, resolve } from "node:path";

const options = Object.fromEntries(
  process.argv.slice(2).reduce((items, value, index, values) => {
    if (value.startsWith("--")) items.push([value.slice(2), values[index + 1]]);
    return items;
  }, []),
);
const required = ["cdp", "url", "png", "dom", "console", "metadata", "marker"];
for (const name of required) if (!options[name]) throw new Error(`Missing --${name}`);

const delay = (milliseconds) => new Promise((done) => setTimeout(done, milliseconds));
const sha256 = async (path) => createHash("sha256").update(await readFile(path)).digest("hex").toUpperCase();
const fetchJson = async (url, init = undefined) => (await fetch(url, init)).json();

const page = await fetchJson(
  `${options.cdp}/json/new?${encodeURIComponent(options.url)}`,
  { method: "PUT" },
);
if (!page?.webSocketDebuggerUrl) throw new Error("Chrome CDP has no page target.");
const socket = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolveOpen, rejectOpen) => {
  socket.onopen = resolveOpen;
  socket.onerror = rejectOpen;
});
let sequence = 0;
const pending = new Map();
const consoleEvents = [];
socket.onmessage = ({ data }) => {
  const message = JSON.parse(data);
  if (message.id && pending.has(message.id)) {
    const { resolveCommand, rejectCommand } = pending.get(message.id);
    pending.delete(message.id);
    message.error ? rejectCommand(new Error(message.error.message)) : resolveCommand(message.result);
  } else if (message.method === "Runtime.consoleAPICalled" || message.method === "Log.entryAdded") {
    consoleEvents.push(message);
  }
};
const command = (method, params = {}) => new Promise((resolveCommand, rejectCommand) => {
  const id = ++sequence;
  pending.set(id, { resolveCommand, rejectCommand });
  socket.send(JSON.stringify({ id, method, params }));
});
await command("Page.enable");
await command("Runtime.enable");
await command("Log.enable");

const deadline = Date.now() + Number(options.timeout ?? 45) * 1000;
let dom = "";
let clicked = !options["click-text"];
while (Date.now() < deadline) {
  const result = await command("Runtime.evaluate", {
    expression: "document.body ? document.body.innerText : ''",
    returnByValue: true,
  });
  dom = String(result.result.value ?? "");
  if (!clicked && dom.includes(options["click-text"])) {
    const clickResult = await command("Runtime.evaluate", {
      expression: `(() => { const target = [...document.querySelectorAll('button')].find((node) => node.innerText.includes(${JSON.stringify(options["click-text"])})); if (!target) return false; target.click(); return true; })()`,
      returnByValue: true,
    });
    clicked = Boolean(clickResult.result.value);
    if (clicked) {
      await delay(Number(options.settle ?? 3) * 1000);
      continue;
    }
  }
  if (clicked && dom.includes(options.marker)) break;
  await delay(500);
}
if (!clicked) throw new Error(`Timed out clicking: ${options["click-text"]}`);
if (!dom.includes(options.marker)) throw new Error(`Timed out waiting for marker: ${options.marker}`);
const screenshot = await command("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
await writeFile(options.png, Buffer.from(screenshot.data, "base64"));
await writeFile(options.dom, `${dom}\n`, "utf8");
await writeFile(options.console, JSON.stringify(consoleEvents, null, 2), "utf8");
const png = await readFile(options.png);
if (png.subarray(0, 8).toString("hex") !== "89504e470d0a1a0a") throw new Error("Screenshot is not PNG.");
const metadata = {
  captured_utc: new Date().toISOString(), url: options.url, marker: options.marker,
  page_url: (await command("Runtime.evaluate", { expression: "location.href", returnByValue: true })).result.value,
  png: { path: basename(options.png), sha256: await sha256(options.png), bytes: png.length },
  dom: { path: basename(options.dom), sha256: await sha256(options.dom) },
  console: { path: basename(options.console), events: consoleEvents.length },
  artifacts: Object.fromEntries(await Promise.all(["stable", "payload", "installer"].map(async (name) => [name, options[`${name}-path`] ? { path: resolve(options[`${name}-path`]), sha256: await sha256(options[`${name}-path`]) } : null]))),
};
await writeFile(options.metadata, JSON.stringify(metadata, null, 2), "utf8");
socket.close();
