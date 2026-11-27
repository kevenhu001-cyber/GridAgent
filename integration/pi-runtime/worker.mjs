import { createInterface } from "node:readline";
import { createGridAgent, projectEvent } from "./agent.mjs";
import { openNativeClient } from "./native-client.mjs";
import { isolatedShell } from "./isolated-shell.mjs";

// Development worker. The trusted host supplies configuration; never accept
// executable paths, model URLs, or credentials from model-generated tool args.
const allowTasks = process.env.GRIDAGENT_NATIVE_TASKS === "1";
const client = openNativeClient({python: process.env.GRIDAGENT_NATIVE_PYTHON,
  workspace: process.env.GRIDAGENT_NATIVE_WORKSPACE, allowTasks});
const agent = createGridAgent({client, provider: process.env.GRIDAGENT_PI_PROVIDER,
  modelId: process.env.GRIDAGENT_PI_MODEL, apiKey: process.env.GRIDAGENT_PI_API_KEY,
  workspace: process.env.GRIDAGENT_NATIVE_WORKSPACE, allowTasks, runShell: isolatedShell(client)});
const emit = (event) => process.stdout.write(JSON.stringify(event) + "\n");
let active = null;
let stopping = false;
agent.subscribe(event => {
  const projected = projectEvent(event);
  if (projected && active !== null) emit({...projected, id: active});
});
const input = createInterface({input: process.stdin, crlfDelay: Infinity});
for await (const line of input) {
  try {
    if (Buffer.byteLength(line) > 65536) throw new Error("Frame exceeds limit");
    const request = JSON.parse(line);
    if (request.method === "abort" && active !== null && request.id === active) {
      agent.abort();
      continue;
    }
    if (request.method !== "prompt" || active !== null || typeof request.id !== "string" ||
      !/^[a-f0-9]{32}$/.test(request.id) || typeof request.text !== "string" || !request.text.trim()) {
      emit({kind: "rejected", id: typeof request.id === "string" ? request.id.slice(0, 32) : null});
      continue;
    }
    active = request.id;
    const id = active;
    void agent.prompt(request.text).then(() => {
      if (agent.state.errorMessage) emit({kind: "error", id, code: "provider_error"});
    }).catch(() => emit({kind: "error", id, code: "agent_failure"}))
      .finally(() => {
        active = null;
        emit({kind: "settled", id});
        if (stopping) client.close();
      });
  } catch {
    emit({kind: "rejected", id: null});
  }
}
stopping = true;
if (active !== null) agent.abort();
else client.close();
