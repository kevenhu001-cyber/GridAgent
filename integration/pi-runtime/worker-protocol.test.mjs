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
  let listener, resolvePrompt, emitJob, aborted = 0;
  const agent = {
    state: {},
    subscribe(fn) { listener = fn; return () => {}; },
    prompt() { emitJob("c".repeat(32));
      listener({kind: "tool_started", tool_id: "tool-1", name: "read"});
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
  const running = serveWorker({agent, projectEvent: e => e, input, output,
    onJob: bind => { emitJob = bind; }});
  const send = request => input.write(JSON.stringify(request) + "\n");
  const id = "a".repeat(32), other = "b".repeat(32);
  await wait("ready");
  send({method: "prompt", id, text: "model"});
  await wait("tool_started");
  await wait("job_submitted");
  send({method: "prompt", id: other, text: "second"});
  await wait("rejected");
  send({method: "abort", id});
  await wait("settled");
  send({method: "abort", id}); // settlement may still be queued at the host
  input.end();
  await running;
  assert.equal(aborted, 1);
  assert.equal(events.filter(e => e.kind === "rejected").length, 1);
  assert.deepEqual(events.find(e => e.kind === "tool_started"),
    {kind: "tool_started", id, tool_id: "tool-1", name: "read"});
  assert.deepEqual(events.find(e => e.kind === "job_submitted"),
    {kind: "job_submitted", id, job_id: "c".repeat(32)});
  assert.deepEqual(events.find(e => e.kind === "rejected"), {kind: "rejected", id: other});
  assert.equal(events.find(e => e.kind === "settled").id, id);
});

test("private tool context is emitted only on explicitly enabled completed turns", async () => {
  for (const enabled of [false, true]) {
    const input = new PassThrough(), output = new PassThrough();
    let listener;
    const agent = {
      state: {messages: []},
      subscribe(fn) { listener = fn; return () => {}; },
      async prompt(prompt) {
        this.state.messages = [
          {role: "user", content: prompt, timestamp: 1},
          {role: "assistant", timestamp: 2, stopReason: "toolUse", content: [
            {type: "toolCall", id: "call_1", name: "read", arguments: {path: "project.py"}},
          ]},
          {role: "toolResult", timestamp: 3, toolCallId: "call_1", toolName: "read",
            content: [{type: "text", text: "result"}], isError: false},
          {role: "assistant", timestamp: 4, stopReason: "stop",
            content: [{type: "text", text: "Done"}]},
        ];
        listener({kind: "text", delta: "Done"});
      },
      abort() {},
    };
    const events = [];
    let buffer = "";
    output.on("data", chunk => {
      buffer += chunk.toString();
      let end;
      while ((end = buffer.indexOf("\n")) >= 0) {
        const event = JSON.parse(buffer.slice(0, end));
        buffer = buffer.slice(end + 1);
        events.push(event);
        if (event.kind === "ready") input.write(JSON.stringify({
          method: "prompt", id: "a".repeat(32), text: "Review",
        }) + "\n");
        if (event.kind === "settled") input.end();
      }
    });
    await serveWorker({agent, projectEvent: event => event, input, output,
      contextOptions: enabled ? {credential: "test-credential", toolNames: ["read"]} : undefined});
    assert.equal(events.filter(event => event.kind === "private_context").length, enabled ? 1 : 0);
    if (enabled) {
      const frame = events.find(event => event.kind === "private_context");
      assert.equal(frame.context.messages[2].content[0].text, "result");
      assert.ok(events.indexOf(frame) < events.findIndex(event => event.kind === "settled"));
    }
  }
});
