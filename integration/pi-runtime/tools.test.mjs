import test from "node:test";
import assert from "node:assert/strict";
import { scientificTools } from "./tools.mjs";
import { projectEvent } from "./agent.mjs";

test("only product-owned tools; no shell or mutation by default", () => {
  const tools = scientificTools({request: async () => ({})});
  assert.ok(tools.some(t => t.name === "scientific_environment"));
  for (const name of ["bash", "shell", "execute_python", "write_project_file", "mcp"])
    assert.ok(!tools.some(t => t.name === name));
});

test("Pi native function dispatch maps to bounded IPC without MCP", async () => {
  const calls = [];
  const tools = scientificTools({request: async (method, args) => {
    calls.push({method, args}); return {status: "queued"};
  }}, {allowTasks: true});
  const execute = tools.find(t => t.name === "execute_python");
  const result = await execute.execute("tool-1", {entry: "study.py"});
  assert.equal(calls[0].method, "job.submit");
  assert.match(calls[0].args.job_id, /^[a-f0-9]{32}$/);
  assert.equal(result.details.status, "queued");
});

test("public projection drops thought and raw tool payloads", () => {
  assert.equal(projectEvent({type: "message_update", assistantMessageEvent: {type: "thinking_delta", delta: "private"}}), null);
  assert.deepEqual(projectEvent({type: "tool_execution_start", toolCallId: "1", toolName: "read", args: {secret: "x"}}),
    {kind: "tool_started", id: "1", name: "read"});
});
