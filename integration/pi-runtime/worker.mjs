import { createGridAgent, projectEvent } from "./agent.mjs";
import { openNativeClient } from "./native-client.mjs";
import { isolatedShell } from "./isolated-shell.mjs";
import { serveWorker } from "./worker-protocol.mjs";

// Trusted host configuration only; no renderer/model-provided executable paths.
const allowTasks = process.env.GRIDAGENT_NATIVE_TASKS === "1";
// Tool execution reports durable job IDs so an interrupted turn can be
// reconciled with any scientific job it may have submitted.
const jobSink = {emit: null};
const onJob = id => jobSink.emit?.(id);
const client = openNativeClient({python: process.env.GRIDAGENT_NATIVE_PYTHON,
  workspace: process.env.GRIDAGENT_NATIVE_WORKSPACE, allowTasks});
try {
  const agent = createGridAgent({client, provider: process.env.GRIDAGENT_PI_PROVIDER,
    modelId: process.env.GRIDAGENT_PI_MODEL, apiKey: process.env.GRIDAGENT_PI_API_KEY,
    workspace: process.env.GRIDAGENT_NATIVE_WORKSPACE, allowTasks,
    runShell: isolatedShell(client, onJob), onJob});
  // Confirm the scoped service is reachable before advertising readiness.
  await client.request("hello");
  await serveWorker({agent, projectEvent, input: process.stdin, output: process.stdout,
    expectContext: process.env.GRIDAGENT_PI_RESTORE_TEXT === "1",
    onJob: emit => { jobSink.emit = emit; },
    contextOptions: process.env.GRIDAGENT_PI_PERSIST_TOOLS === "1" &&
      process.env.GRIDAGENT_PI_PROVIDER === "openai" && process.env.GRIDAGENT_PI_API_KEY?.trim() ?
      {credential: process.env.GRIDAGENT_PI_API_KEY, toolNames: agent.state.tools.map(tool => tool.name)} : undefined});
} finally {
  client.close();
}
