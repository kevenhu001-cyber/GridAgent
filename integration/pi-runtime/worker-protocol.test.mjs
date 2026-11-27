import test from "node:test";
import assert from "node:assert/strict";
import { PassThrough, Readable } from "node:stream";
import { frames, serveWorker } from "./worker-protocol.mjs";

test("bounded frames recover after oversized input and reject partial EOF", async () => {
  const input = Readable.from([Buffer.alloc(70_000, 65), Buffer.from("\n{}\npartial")]);
  const found = [];
  for await (const frame of frames(input)) found.push(frame);
  assert.deepEqual(found, [null, "{}", null]);
});

test("worker correlates tool and request IDs, rejects concurrent prompt, and aborts", async () => {
  const input = new PassThrough(), output = new PassThrough();
  let listener, resolvePrompt, aborted = 0;
  const agent = {
    state: {},
    subscribe(fn) { listener = fn; return () => {}; },
    prompt() { listener({kind: "tool_started", tool_id: "tool-1", name: "read"});
      return new Promise(resolve => { resolvePrompt = resolve; }); },
    abort() { aborted++; resolvePrompt?.(); },
  };
  const events = [];
  let buffer = "";
  const waiters = [];
  output.on("data", chunk => {
    buffer += chunk.toString();
    let newline;
    while ((newline = buffer.indexOf("\n")) >= 0) {
      events.push(JSON.parse(buffer.slice(0, newline)));
      buffer = buffer.slice(newline + 1);
    }
    for (const wake of waiters.splice(0)) wake();
  });
  async function wait(kind) {
    while (!events.some(e => e.kind === kind)) {
      await new Promise(resolve => waiters.push(resolve));
    }
  }
  const running = serveWorker({agent, projectEvent: e => e, input, output});
  const send = request => input.write(JSON.stringify(request) + "\n");
  const id = "a".repeat(32), other = "b".repeat(32);
  await wait("ready");
  send({method: "prompt", id, text: "model"});
  await wait("tool_started");
  send({method: "prompt", id: other, text: "second"});
  await wait("rejected");
  send({method: "abort", id});
  await wait("settled");
  input.end();
  await running;
  assert.equal(aborted, 1);
  assert.deepEqual(events.find(e => e.kind === "tool_started"),
    {kind: "tool_started", id, tool_id: "tool-1", name: "read"});
  assert.deepEqual(events.find(e => e.kind === "rejected"), {kind: "rejected", id: other});
  assert.equal(events.find(e => e.kind === "settled").id, id);
});
