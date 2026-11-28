import { once } from "node:events";
import { isCompleteTextTurn, restoreTextContext } from "./text-context.mjs";

const MAX_FRAME = 64 * 1024;
const validId = id => typeof id === "string" && /^[a-f0-9]{32}$/.test(id);

/** Bound allocation before decoding, discard oversized lines until the next newline. */
export async function* frames(input) {
  let parts = [], size = 0, overflow = false;
  for await (const value of input) {
    const chunk = Buffer.isBuffer(value) ? value : Buffer.from(value);
    let start = 0;
    while (start < chunk.length) {
      const end = chunk.indexOf(10, start);
      const part = chunk.subarray(start, end < 0 ? chunk.length : end);
      size += part.length;
      if (size >= MAX_FRAME) { overflow = true; parts = []; }
      else if (!overflow) parts.push(part);
      if (end < 0) break;
      yield overflow ? null : Buffer.concat(parts, size).toString("utf8");
      parts = []; size = 0; overflow = false; start = end + 1;
    }
  }
  if (size || overflow) yield null; // never accept an unterminated request
}

/** One in-flight prompt; request IDs and tool-call IDs have distinct fields. */
export async function serveWorker({agent, projectEvent, input, output, expectContext = false, onJob}) {
  let active = null, pending = null;
  let streamed = "", cancelled = false;
  const requests = frames(input);
  if (expectContext) {
    const first = await requests.next();
    if (!first.value) throw new Error("Missing Pi text context");
    restoreTextContext(agent, JSON.parse(first.value));
  }
  let writeQueue = Promise.resolve();
  let queuedBytes = 0;
  let failed = false;
  const emit = event => {
    if (failed) return;
    const line = JSON.stringify(event) + "\n";
    const size = Buffer.byteLength(line);
    if (size > MAX_FRAME || queuedBytes + size > 1024 * 1024) {
      failed = true;
      agent.abort();
      input.destroy(new Error("Worker output exceeded limit"));
      return;
    }
    queuedBytes += size;
    writeQueue = writeQueue.then(async () => {
      if (!output.write(line)) await once(output, "drain");
    }).catch(() => {
      failed = true; agent.abort(); input.destroy();
    }).finally(() => { queuedBytes -= size; });
  };
  // Tools report a durable job ID before dispatch; attach it to the active turn.
  if (typeof onJob === "function") {
    onJob(jobId => {
      if (active !== null && typeof jobId === "string" && /^[a-f0-9]{32}$/.test(jobId)) {
        emit({kind: "job_submitted", id: active, job_id: jobId});
      }
    });
  }
  const unsubscribe = agent.subscribe(event => {
    const projected = projectEvent(event);
    if (!projected || active === null) return;
    if (projected.kind === "text" && streamed !== null) {
      streamed += projected.delta;
      if (streamed.length > MAX_FRAME) streamed = null;
    }
    emit({...projected, id: active});
  });
  emit({kind: "ready", version: 1, ...(expectContext ? {restored: true} : {})});
  try {
    for await (const line of requests) {
      let request;
      try { request = JSON.parse(line ?? ""); } catch { request = null; }
      if (!request || !validId(request.id)) {
        emit({kind: "rejected", id: null});
        continue;
      }
      if (request.method === "abort") {
        // A host can request cancellation after settlement was queued but
        // before it observed that event. Stale aborts are harmless no-ops.
        if (request.id === active) { cancelled = true; agent.abort(); }
        continue;
      }
      if (request.method !== "prompt" || active !== null ||
          typeof request.text !== "string" || !request.text.trim()) {
        emit({kind: "rejected", id: request.id});
        continue;
      }
      active = request.id;
      const id = active;
      const priorCount = agent.state.messages?.length;
      streamed = "";
      cancelled = false;
      let contextOk = false;
      pending = Promise.resolve().then(() => agent.prompt(request.text)).then(() => {
        if (agent.state.errorMessage) emit({kind: "error", id, code: "provider_error"});
        else if (!cancelled && streamed !== null && priorCount !== undefined) {
          contextOk = isCompleteTextTurn(agent.state.messages.slice(priorCount), request.text, streamed);
        }
      }).catch(() => emit({kind: "error", id, code: "agent_failure"}))
        .finally(() => {
          active = null;
          emit({kind: "settled", id, ...(contextOk ? {context_ok: true} : {})});
        });
    }
  } finally {
    if (active !== null) agent.abort();
    if (pending) await pending;
    if (typeof unsubscribe === "function") unsubscribe();
    await writeQueue;
  }
}
