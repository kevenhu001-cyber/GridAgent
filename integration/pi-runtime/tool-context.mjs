import { restoreTextContext } from "./text-context.mjs";
// Private model-context projection, not a public transcript or disk format.
// Persistence is opt-in and host-owned; never forward this to the renderer.
const MAX_BYTES = 48 * 1024;
const MAX_MESSAGES = 64;
const MAX_PARTS = 32;
const MAX_DEPTH = 12;
const bytes = value => Buffer.byteLength(value, "utf8");
const plain = value => value !== null && typeof value === "object" &&
  (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null);
const validId = value => typeof value === "string" && /^[A-Za-z0-9_.:|=-]{1,256}$/.test(value);
const sensitiveKey = /^(?:api[-_]?key|authorization|access[-_]?token|refresh[-_]?token|password|secret|credential)$/i;

function reject() { throw new Error("Pi tool context is not safely restorable"); }

function text(value, secret) {
  if (typeof value !== "string" || bytes(value) > MAX_BYTES || value.includes(secret)) reject();
  return value;
}

// Only ordinary JSON values; no details, provider payloads, executable objects,
// prototype keys, non-finite values, or known provider credentials.
function json(value, secret, depth = 0) {
  if (depth > MAX_DEPTH) reject();
  if (typeof value === "string") return text(value, secret);
  if (value === null || typeof value === "boolean" ||
      (typeof value === "number" && Number.isFinite(value))) return value;
  if (Array.isArray(value)) {
    if (value.length > 1024) reject();
    return value.map(item => json(item, secret, depth + 1));
  }
  if (!plain(value)) reject();
  const entries = Object.entries(value);
  if (entries.length > 256) reject();
  return Object.fromEntries(entries.map(([key, item]) => {
    if (sensitiveKey.test(key) || ["__proto__", "constructor", "prototype"].includes(key)) reject();
    return [text(key, secret), json(item, secret, depth + 1)];
  }));
}

function parts(content) {
  if (!Array.isArray(content) || content.length > MAX_PARTS) reject();
  return content;
}

function userText(content, secret) {
  if (typeof content === "string") return text(content, secret);
  const list = parts(content);
  if (list.length !== 1 || list[0]?.type !== "text") reject();
  return text(list[0].text, secret);
}

function textParts(content, secret) {
  return parts(content).map(part => {
    if (part?.type !== "text") reject();
    return {type: "text", text: text(part.text, secret)};
  });
}

/**
 * Project one complete, successful SDK turn. Preserve matched tool calls and
 * their text results; discard thinking, signatures, usage, and raw details.
 * Uncertain, truncated, unregistered, image-bearing or oversized turns fail
 * closed. This function performs no tool or provider calls.
 */
export function projectToolTurn(messages, {toolNames, credential}) {
  try {
    if (!Array.isArray(messages) || messages.length < 4 || messages.length > MAX_MESSAGES ||
        typeof credential !== "string" || !credential || !Array.isArray(toolNames)) reject();
    const allowed = new Set(toolNames);
    const first = messages[0];
    if (first?.role !== "user" || !Number.isSafeInteger(first.timestamp)) reject();
    const prompt = userText(first.content, credential);
    if (!prompt.trim()) reject();
    const projected = [{role: "user", content: prompt, timestamp: first.timestamp}];
    const seen = new Set();
    let pending = new Map(), sawTool = false, finished = false;
    for (const message of messages.slice(1)) {
      if (finished || !Number.isSafeInteger(message?.timestamp)) reject();
      if (message.role === "assistant") {
        if (pending.size) reject();
        const content = [];
        for (const part of parts(message.content)) {
          if (part?.type === "thinking") continue;
          if (part?.type === "text") {
            content.push({type: "text", text: text(part.text, credential)});
          } else if (part?.type === "toolCall") {
            if (!validId(part.id) || seen.has(part.id) || !allowed.has(part.name) ||
                !plain(part.arguments)) reject();
            seen.add(part.id);
            pending.set(part.id, part.name);
            sawTool = true;
            content.push({type: "toolCall", id: text(part.id, credential),
              name: text(part.name, credential), arguments: json(part.arguments, credential)});
          } else reject();
        }
        if (pending.size) {
          if (message.stopReason !== "toolUse") reject();
        } else {
          if (message.stopReason !== "stop" ||
              !content.some(part => part.type === "text" && part.text.trim())) reject();
          finished = true;
        }
        projected.push({role: "assistant", content, timestamp: message.timestamp,
          stopReason: message.stopReason});
      } else if (message.role === "toolResult") {
        if (!pending.has(message.toolCallId) || pending.get(message.toolCallId) !== message.toolName ||
            typeof message.isError !== "boolean") reject();
        pending.delete(message.toolCallId);
        projected.push({role: "toolResult", toolCallId: message.toolCallId, toolName: message.toolName,
          content: textParts(message.content, credential), isError: message.isError,
          timestamp: message.timestamp});
      } else reject();
    }
    if (!sawTool || !finished || pending.size) reject();
    const frame = {version: 1, messages: projected};
    // Reject credentials even when split over adjacent visible text parts.
    const visible = projected.flatMap(message => typeof message.content === "string" ?
      [message.content] : message.content.filter(part => part.type === "text").map(part => part.text));
    if (visible.join("").includes(credential) || bytes(JSON.stringify(frame)) > MAX_BYTES) reject();
    return frame;
  } catch {
    return null;
  }
}

const zeroUsage = () => ({input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
  cost: {input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0}});

/**
 * Seed a fresh Pi SDK state from validated completed turns. Only the same
 * authorized model/session should call this once the host contract exists.
 * No prompting, replay, tool dispatch or public UI events occur here.
 */
export function restoreToolContext(agent, frames, options) {
  if (!Array.isArray(frames) || !frames.length || frames.length > MAX_MESSAGES ||
      !Array.isArray(agent.state.messages) || agent.state.messages.length) reject();
  const messages = [];
  const ids = new Set();
  let totalBytes = 0;
  for (const frame of frames) {
    if (!plain(frame) || frame.version !== 1) reject();
    const clean = projectToolTurn(frame.messages, options);
    if (!clean) reject();
    totalBytes += bytes(JSON.stringify(clean));
    if (totalBytes > MAX_BYTES || messages.length + clean.messages.length > MAX_MESSAGES) reject();
    for (const message of clean.messages) {
      if (message.role === "assistant") {
        for (const part of message.content) {
          if (part.type === "toolCall") {
            if (ids.has(part.id)) reject();
            ids.add(part.id);
          }
        }
        const {api, provider, id: model} = agent.state.model;
        messages.push({...message, api, provider, model, usage: zeroUsage()});
      } else messages.push(message);
    }
  }
  agent.state.messages = messages;
}

/** Restore an ordered mix of verified text and completed tool turns atomically. */
export function restoreMixedContext(agent, frame, options) {
  if (frame?.method !== "restore_mixed" || frame.version !== 1 ||
      !Array.isArray(frame.turns) || !frame.turns.length || frame.turns.length > MAX_MESSAGES ||
      bytes(JSON.stringify(frame)) > MAX_BYTES ||
      !Array.isArray(agent.state.messages) || agent.state.messages.length) reject();
  const messages = [], ids = new Set();
  for (const turn of frame.turns) {
    const scratch = {state: {model: agent.state.model, messages: []}};
    if (turn?.kind === "text") {
      text(turn.user, options.credential);
      text(turn.assistant, options.credential);
      restoreTextContext(scratch, {method: "restore_text", version: 1,
        turns: [{user: turn.user, assistant: turn.assistant, timestamp: turn.timestamp}]});
    } else if (turn?.kind === "tool") {
      restoreToolContext(scratch, [turn.context], options);
    } else reject();
    for (const message of scratch.state.messages) {
      if (message.role === "assistant") for (const part of message.content) {
        if (part.type === "toolCall") {
          if (ids.has(part.id)) reject();
          ids.add(part.id);
        }
      }
      messages.push(message);
    }
    if (messages.length > MAX_MESSAGES) reject();
  }
  agent.state.messages = messages;
}
