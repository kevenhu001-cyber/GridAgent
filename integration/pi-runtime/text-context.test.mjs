import assert from "node:assert/strict";
import test from "node:test";
import { once } from "node:events";
import { PassThrough } from "node:stream";
import { createAssistantMessageEventStream } from "@earendil-works/pi-ai";
import { createGridAgent, projectEvent } from "./agent.mjs";
import { isCompleteTextTurn } from "./text-context.mjs";
import { serveWorker } from "./worker-protocol.mjs";

test("rejects incomplete text, tool calls and non-stop completions", () => {
  const user = {role: "user", content: "Study"};
  const assistant = {role: "assistant", stopReason: "stop", content: [
    {type: "thinking", thinking: "private"}, {type: "text", text: "Result"},
  ]};
  assert.equal(isCompleteTextTurn([user, assistant], "Study", "Result"), true);
  assert.equal(isCompleteTextTurn([user, assistant], "Study", "Res"), false);
  assert.equal(isCompleteTextTurn([user, {...assistant, stopReason: "length"}], "Study", "Result"), false);
  assert.equal(isCompleteTextTurn([user, {...assistant,
    content: [...assistant.content, {type: "toolCall"}]}], "Study", "Result"), false);
});

test("Pi SDK uses restored text only after receiving a new prompt", {timeout: 5000}, async () => {
  const agent = createGridAgent({
    client: {request: async () => assert.fail("unexpected scientific call")},
    provider: "openai", modelId: "gpt-5.4", apiKey: "test-only", workspace: process.cwd(),
  });
  const calls = [];
  agent.streamFunction = (model, context) => {
    calls.push(structuredClone(context.messages));
    const stream = createAssistantMessageEventStream();
    const base = {role: "assistant", api: model.api, provider: model.provider, model: model.id,
      timestamp: Date.now(), stopReason: "stop",
      usage: {input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
        cost: {input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0}}};
    const final = {...base, content: [{type: "text", text: "Follow-up answer"}]};
    stream.push({type: "start", partial: {...base, content: []}});
    stream.push({type: "text_delta", contentIndex: 0, delta: "Follow-up answer", partial: final});
    stream.push({type: "done", reason: "stop", message: final});
    return stream;
  };
  const input = new PassThrough(), output = new PassThrough();
  const running = serveWorker({agent, projectEvent, input, output, expectContext: true});
  const send = value => input.write(JSON.stringify(value) + "\n");
  const ready = once(output, "data");
  send({method: "restore_text", version: 1, turns: [
    {user: "First prompt", assistant: "First answer", timestamp: 1000},
  ]});
  assert.deepEqual(JSON.parse(String((await ready)[0])), {kind: "ready", version: 1, restored: true});
  assert.equal(calls.length, 0);
  const events = [];
  output.on("data", chunk => {
    const event = JSON.parse(String(chunk));
    events.push(event);
    if (event.kind === "settled") input.end();
  });
  send({method: "prompt", id: "a".repeat(32), text: "New prompt"});
  await running;
  assert.equal(calls.length, 1);
  const delivered = calls[0].filter(message => ["user", "assistant"].includes(message.role));
  assert.deepEqual(delivered.map(message => message.role), ["user", "assistant", "user"]);
  assert.equal(delivered[0].content, "First prompt");
  assert.deepEqual(delivered[1].content, [{type: "text", text: "First answer"}]);
  assert.match(JSON.stringify(delivered[2].content), /New prompt/);
  assert.equal(events.find(event => event.kind === "settled")?.context_ok, true);
});
