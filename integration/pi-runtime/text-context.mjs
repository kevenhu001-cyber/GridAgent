/** The live SDK state is the authority for whether public deltas are enough
 * to reconstruct a turn. Provider payloads and reasoning are never exported. */
export function isCompleteTextTurn(messages, prompt, streamed) {
  if (!messages || messages.length !== 2 || !streamed.trim()) return false;
  const [user, assistant] = messages;
  if (user.role !== "user" || assistant.role !== "assistant" || assistant.stopReason !== "stop") return false;
  const content = user.content;
  const matches = typeof content === "string" ? content === prompt :
    content.length === 1 && content[0].type === "text" && content[0].text === prompt;
  return matches && assistant.content.every(part => part.type === "text" || part.type === "thinking") &&
    assistant.content.filter(part => part.type === "text").map(part => part.text).join("") === streamed;
}

/** Seed the existing SDK transcript without prompting or running any tools. */
export function restoreTextContext(agent, frame) {
  if (frame?.method !== "restore_text" || frame.version !== 1 ||
      !Array.isArray(frame.turns) || !frame.turns.length) throw new Error("Invalid Pi text context");
  const {api, provider, id: model} = agent.state.model;
  const messages = [];
  for (const turn of frame.turns) {
    const {user, assistant, timestamp} = turn;
    if (typeof user !== "string" || !user.trim() || typeof assistant !== "string" ||
        !assistant.trim() || !Number.isSafeInteger(timestamp)) throw new Error("Invalid restored Pi turn");
    messages.push({role: "user", content: user, timestamp}, {
      role: "assistant", content: [{type: "text", text: assistant}], timestamp,
      api, provider, model, stopReason: "stop",
      usage: {input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
        cost: {input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0}},
    });
  }
  agent.state.messages = [...agent.state.messages, ...messages];
}
