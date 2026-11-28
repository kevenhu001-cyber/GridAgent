import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile, readFile, realpath, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { vmRequest, SDK_VERSION } from "./policy.mjs";

// Developer-only qualification: no project files, keys, user commands or
// automatic backend selection. Do not use a production host with secrets.
if (process.platform !== "win32" || process.arch !== "x64" ||
    process.argv.length !== 3 || process.argv[2] !== "--experimental-vm") {
  throw new Error("Requires Windows x64 and explicit --experimental-vm");
}
const {runJson} = await import("@microsoft/mxc-sdk/v1/dev");
const root = await realpath(await mkdtemp(join(tmpdir(), "gridagent-mxc-")));
const input = join(root, "input");
const output = join(root, "output");
const privateFile = join(root, "private.txt");
await mkdir(input);
await mkdir(output);
await writeFile(join(input, "sample.txt"), "gridagent-fixture");
await writeFile(privateFile, "synthetic-private");
const request = vmRequest({input, output, privateFile});
let confirmed = false;
const start = performance.now();
try {
  const result = await runJson(JSON.stringify(request), {experimental: true});
  assert.equal(result.timedOut, false, "MXC timeout");
  assert.equal(result.exitCode, 0, "MXC guest workload failed");
  assert.match(result.stdout, /gridagent-qualified/);
  assert.equal(await readFile(join(output, "result.txt"), "utf8"), "gridagent-qualified");
  assert.equal(await readFile(join(input, "sample.txt"), "utf8"), "gridagent-fixture");
  assert.equal(await readFile(privateFile, "utf8"), "synthetic-private");
  confirmed = true;
  console.log(JSON.stringify({
    sdk: SDK_VERSION, backend: "windows_sandbox", elapsed_ms: Math.round(performance.now() - start),
    fixture_read: true, readonly_input: true, unshared_read_denied: true, output_write: true,
    production_qualified: false,
  }));
} finally {
  // Keep synthetic fixtures on failure for manual recovery. Never force
  // reclaim another Windows Sandbox instance or retry on the unrestricted host.
  if (confirmed) await rm(root, {recursive: true, force: true});
  else console.error("Qualification failed; inspect MXC cleanup and fixture directory:", root);
}
