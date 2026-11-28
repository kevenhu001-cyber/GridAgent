import assert from "node:assert/strict";
import { test } from "node:test";
import { vmRequest } from "./policy.mjs";

const fixture = {
  input: "C:\\Temp\\gridagent-mxc\\input",
  output: "C:\\Temp\\gridagent-mxc\\output",
  privateFile: "C:\\Temp\\gridagent-mxc\\private.txt",
};

test("policy explicitly selects VM and maps only fixture directories", () => {
  const request = vmRequest(fixture);
  assert.equal(request.containment, "windows_sandbox");
  assert.equal(request.version, "1.1.0-alpha");
  assert.deepEqual(request.filesystem, {
    readonlyPaths: [fixture.input], readwritePaths: [fixture.output],
  });
  assert.equal(request.process.timeout, 120000);
  assert.equal(Object.hasOwn(request, "network"), false);
  assert.equal(Object.hasOwn(request.process, "environment"), false);
  const script = Buffer.from(request.process.commandLine.split(" ").at(-1), "base64").toString("utf16le");
  assert.match(script, /read-only input was writable/);
  assert.match(script, /unshared host file was readable/);
});

test("rejects unrelated output, traversal, UNC and overlapping fixture grants", () => {
  for (const change of [
    {output: "C:\\Other\\output"},
    {input: "C:\\Temp\\gridagent-mxc\\other\\..\\input"},
    {input: "\\\\server\\share\\input"},
    {output: fixture.input},
    {privateFile: fixture.output},
  ]) assert.throws(() => vmRequest({...fixture, ...change}));
});
