import assert from "node:assert/strict";
import test from "node:test";
import { projectToolTurn, restoreToolContext, restoreMixedContext } from "./tool-context.mjs";

const options = {toolNames: ["scientific_job_status"], credential: "provider-secret-test"};
const job = "a".repeat(32);
const fixture = () => [
  {role: "user", content: "Check the job", timestamp: 1},
  {role: "assistant", timestamp: 2, stopReason: "toolUse", content: [
    {type: "thinking", thinking: "private reasoning", thinkingSignature: "private signature"},
    {type: "toolCall", id: "call_1", name: "scientific_job_status",
      arguments: {job_id: job}, thoughtSignature: "private signature"},
  ]},
  {role: "toolResult", timestamp: 3, toolCallId: "call_1", toolName: "scientific_job_status",
    content: [{type: "text", text: '{"state":"finished"}'}], isError: false,
    details: {secret: "raw details"}},
  {role: "assistant", timestamp: 4, stopReason: "stop",
    content: [{type: "text", text: "The job finished."}], usage: {private: true}},
];

test("project only complete matched tool history; omit reasoning, signatures and raw details", () => {
  const frame = projectToolTurn(fixture(), options);
  assert.ok(frame);
  assert.equal(frame.messages[1].content[0].arguments.job_id, job);
  assert.equal(frame.messages[2].toolCallId, "call_1");
  assert.equal(frame.messages[2].content[0].text, '{"state":"finished"}');
  assert.doesNotMatch(JSON.stringify(frame), /private|signature|raw details|provider-secret/);
});

test("reject interrupted, mismatched, unknown, duplicate and credential-bearing context", () => {
  const variants = [
    messages => messages.pop(),
    messages => { messages[2].toolCallId = "other"; },
    messages => { messages[1].content[1].name = "unknown"; },
    messages => { messages[1].content.push({...messages[1].content[1]}); },
    messages => { messages[1].content[1].arguments.api_key = "different-key"; },
    messages => { messages[2].content[0].text = options.credential; },
    messages => { messages[3].stopReason = "length"; },
    messages => { messages[2].content.push({type: "image", data: "x"}); },
    messages => { messages[2].content[0].text = "x".repeat(49000); },
    messages => { messages[3].content = [{type: "text", text: "provider-"},
      {type: "text", text: "secret-test"}]; },
  ];
  for (const change of variants) {
    const messages = fixture();
    change(messages);
    assert.equal(projectToolTurn(messages, options), null);
  }
});

test("restore is atomic and never prompts, replays tools or copies provider metadata", () => {
  const agent = {state: {messages: [], model: {api: "test-api", provider: "openai", id: "test-model"}},
    prompt: () => assert.fail("must not prompt"),
    tools: [{execute: () => assert.fail("must not execute")}]};
  const frame = projectToolTurn(fixture(), options);
  assert.throws(() => restoreToolContext(agent, [frame, frame], options));
  assert.deepEqual(agent.state.messages, []);
  restoreToolContext(agent, [frame], options);
  assert.deepEqual(agent.state.messages.map(message => message.role),
    ["user", "assistant", "toolResult", "assistant"]);
  assert.equal(agent.state.messages[1].model, "test-model");
  assert.equal(agent.state.messages[2].toolCallId, "call_1");
  assert.throws(() => restoreToolContext(agent, [frame], options));
});

test("mixed history restores text and tool turns in order, atomically", () => {
  const agent = {state: {messages: [], model: {api: "test-api", provider: "openai", id: "test-model"}}};
  const tool = {kind: "tool", context: projectToolTurn(fixture(), options)};
  const text = {kind: "text", user: "Prior question", assistant: "Prior answer", timestamp: 0};
  const seed = {method: "restore_mixed", version: 1, turns: [text, tool, text]};
  assert.throws(() => restoreMixedContext(agent, {...seed, turns: [text, tool, tool]}, options));
  assert.deepEqual(agent.state.messages, []);
  restoreMixedContext(agent, seed, options);
  assert.deepEqual(agent.state.messages.map(m => m.role), ["user", "assistant", "user", "assistant", "toolResult", "assistant", "user", "assistant"]);
});
