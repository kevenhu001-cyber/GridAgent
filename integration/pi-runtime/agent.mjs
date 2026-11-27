import { Agent } from "@earendil-works/pi-agent-core";
import { createModels } from "@earendil-works/pi-ai";
import { openaiProvider } from "@earendil-works/pi-ai/providers/openai";
import { anthropicProvider } from "@earendil-works/pi-ai/providers/anthropic";
import { googleProvider } from "@earendil-works/pi-ai/providers/google";
import { scientificTools } from "./tools.mjs";
import { defaultTools } from "./default-tools.mjs";

export const SYSTEM_PROMPT = "You are GridAgent, an LLM-led scientific engineering agent. " +
  "Formulate physical and mathematical models, choose numerical methods, author and revise code, " +
  "inspect actual results and distinguish numerical convergence from independent validation. " +
  "Use the built-in Pi coding tools and GridAgent scientific tools within the authorized workspace; never bypass the sandbox or fabricate results. " +
  "An asynchronous job submission is not a completed calculation. Report pending work honestly. " +
  "Preserve fixed user requirements and ask for authorization when needed.";

export function createGridAgent({client, provider, modelId, apiKey, workspace, allowTasks = false, runShell}) {
  const models = createModels();
  const factories = {openai: openaiProvider, anthropic: anthropicProvider, google: googleProvider};
  if (!Object.hasOwn(factories, provider)) throw new Error("Unsupported model provider");
  models.setProvider(factories[provider]());
  const model = models.getModel(provider, modelId);
  if (!model) throw new Error("Unknown model for selected provider");
  const tools = [...defaultTools(client, {workspace, allowTasks, runShell}),
    ...scientificTools(client, {allowTasks})];
  const agent = new Agent({
    initialState: {systemPrompt: SYSTEM_PROMPT, model, tools},
    streamFn: models.streamSimple.bind(models),
    getApiKey: async () => apiKey,
    toolExecution: "sequential",
    beforeToolCall: async ({toolCall}) => tools.some(t => t.name === toolCall.name) ?
      undefined : {block: true, reason: "Tool not permitted"},
  });
  return agent;
}

/** Public UI events only: no chain of thought, tool arguments, credentials or raw provider payload. */
export function projectEvent(event) {
  switch (event.type) {
    case "agent_start": return {kind: "started"};
    case "agent_end": return {kind: "finished"};
    case "message_update":
      if (event.assistantMessageEvent.type === "text_delta")
        return {kind: "text", delta: event.assistantMessageEvent.delta};
      return null;
    case "tool_execution_start":
      return {kind: "tool_started", id: event.toolCallId, name: event.toolName};
    case "tool_execution_end":
      return {kind: "tool_finished", id: event.toolCallId, name: event.toolName, error: event.isError};
    default: return null;
  }
}
