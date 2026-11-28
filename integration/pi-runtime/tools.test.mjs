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
  const calls = [], jobs = [];
  const tools = scientificTools({request: async (method, args) => {
    calls.push({method, args}); return {status: "queued"};
  }}, {allowTasks: true, onJob: id => jobs.push(id)});
  const execute = tools.find(t => t.name === "execute_python");
  const result = await execute.execute("tool-1", {entry: "study.py"});
  assert.equal(calls[0].method, "job.submit");
  assert.match(calls[0].args.job_id, /^[a-f0-9]{32}$/);
  assert.deepEqual(jobs, [calls[0].args.job_id]);
  assert.equal(result.details.status, "queued");
});

test("public projection drops thought and raw tool payloads", () => {
  assert.equal(projectEvent({type: "message_update", assistantMessageEvent: {type: "thinking_delta", delta: "private"}}), null);
  assert.deepEqual(projectEvent({type: "tool_execution_start", toolCallId: "1", toolName: "read", args: {secret: "x"}}),
    {kind: "tool_started", tool_id: "1", name: "read"});
});

import { defaultTools } from "./default-tools.mjs";
import { isolatedShell } from "./isolated-shell.mjs";
import { resolve } from "node:path";

test("Pi default tools retained and file operations use native IPC", async () => {
  const calls = [];
  const workspace = resolve("test-workspace");
  const client = {request: async (method, args) => {
    calls.push({method, args});
    if (method === "workspace.files") return {files: [{path: "study.py"}]};
    if (method === "workspace.read") return {text: "print(1)\n", sha256: "a".repeat(64), next_offset: null};
    if (method === "workspace.write") return {sha256: "b".repeat(64)};
    throw new Error("Unexpected native operation");
  }};
  const tools = defaultTools(client, {workspace, allowTasks: true});
  for (const name of ["read", "write", "edit", "bash", "powershell", "grep", "find", "ls"])
    assert.ok(tools.some(t => t.name === name), name);
  const read = tools.find(t => t.name === "read");
  const result = await read.execute("1", {path: "study.py"});
  assert.match(result.content[0].text, /print\(1\)/);
  await assert.rejects(() => read.execute("2", {path: "../secret.txt"}));
  await tools.find(t => t.name === "write").execute("3", {path: "study.py", content: "print(2)"});
  assert.equal(calls.find(c => c.method === "workspace.write").args.expected_sha256, "a".repeat(64));
});

test("Pi shell routes to native job, not host command", async () => {
  const calls = [], jobs = [];
  let output = "";
  const shell = isolatedShell({request: async (method, args) => {
    calls.push({method, args});
    return {status: "ok", exit_code: 0, stdout_stderr_tail: "42"};
  }}, id => jobs.push(id));
  const result = await shell("powershell", "Write-Output 42", {onData: b => {output += b.toString();}});
  assert.equal(calls[0].method, "job.submit_shell");
  assert.equal(calls[0].args.shell, "powershell");
  assert.deepEqual(jobs, [calls[0].args.job_id]);
  assert.equal(result.exitCode, 0);
  assert.equal(output, "42");
});
