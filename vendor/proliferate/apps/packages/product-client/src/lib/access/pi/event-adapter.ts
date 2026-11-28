import type { SessionEvent, SessionEventEnvelope, TranscriptItemPayload } from "@anyharness/sdk";
import type { PiEvent } from "../../../host/desktop-bridge";

/**
 * Transport projection only. The existing SDK transcript reducer owns
 * message/tool state, and ProductClient owns history and rendering.
 * One instance per materialized product session; sequence resumes from
 * the durable event log, not an independent renderer conversation store.
 */
export class PiEventAdapter {
  private seq: number;
  private active: {requestId: string; turnId: string; textId: string | null;
    tools: Map<string, {itemId: string; name: string}>; seenTools: Set<string>;
    failed: boolean; cancellationRequested: boolean; jobs: string[]} | null = null;
  private readonly sessionId: string;
  private readonly now: () => string;
  constructor(sessionId: string, afterSeq = 0, now = () => new Date().toISOString()) {
    if (!sessionId || !Number.isSafeInteger(afterSeq) || afterSeq < 0) throw new Error("Invalid Pi session cursor");
    this.sessionId = sessionId;
    this.seq = afterSeq;
    this.now = now;
  }

  private envelope(event: SessionEvent, itemId?: string): SessionEventEnvelope {
    return {sessionId: this.sessionId, seq: ++this.seq, timestamp: this.now(),
      turnId: this.active?.turnId ?? null, itemId: itemId ?? null, event};
  }

  private item(kind: TranscriptItemPayload["kind"], status: TranscriptItemPayload["status"],
    extra: Partial<TranscriptItemPayload> = {}): TranscriptItemPayload {
    return { ...extra, kind, status, sourceAgentKind: "pi" };
  }

  /** Called only after native prompt admission, using the existing outbox ID. */
  begin(requestId: string, promptId: string, text: string, jobs: string[] = []): SessionEventEnvelope[] {
    if (this.active || !/^[a-f0-9]{32}$/.test(requestId) || !promptId || !text.trim()) throw new Error("Invalid Pi turn admission");
    if (!Array.isArray(jobs) || jobs.length > 32 || jobs.some(job => !/^[a-f0-9]{32}$/.test(job)))
      throw new Error("Invalid Pi turn jobs");
    this.active = {requestId, turnId: requestId, textId: null, tools: new Map(), seenTools: new Set(),
      failed: false, cancellationRequested: false, jobs: [...jobs]};
    return [this.envelope({type: "turn_started"}),
      this.envelope({type: "item_completed", item: this.item("user_message", "completed",
        {promptId, contentParts: [{type: "text", text}]})}, requestId + ":user")];
  }

  noteCancellation(requestId: string) {
    if (this.active?.requestId === requestId) this.active.cancellationRequested = true;
  }

  private finishText(out: SessionEventEnvelope[]) {
    const turn = this.active;
    if (turn?.textId) {
      out.push(this.envelope({type: "item_completed", item: this.item("assistant_message", "completed")}, turn.textId));
      turn.textId = null;
    }
  }

  private toolPayload(id: string, name: string, status: TranscriptItemPayload["status"]) {
    return this.item("tool_invocation", status, {title: name, nativeToolName: name, toolCallId: id,
      contentParts: [{type: "tool_call", title: name, nativeToolName: name, toolCallId: id, toolKind: "other"}]});
  }

  private failOpenTools(out: SessionEventEnvelope[]) {
    const turn = this.active;
    if (!turn) return;
    for (const [id, tool] of turn.tools) out.push(this.envelope({type: "item_completed",
      item: this.toolPayload(id, tool.name, "failed")}, tool.itemId));
    turn.tools.clear();
  }

  private failureMessage(message: string) {
    const jobs = this.active?.jobs ?? [];
    return jobs.length ? `${message} Unconfirmed scientific jobs: ${jobs.join(", ")}.` : message;
  }

  private fail(out: SessionEventEnvelope[], code: string, message: string) {
    if (!this.active) return;
    this.finishText(out);
    this.failOpenTools(out);
    out.push(this.envelope({type: "error", code, message: this.failureMessage(message)},
      this.active.turnId + ":error:" + (this.seq + 1)));
    this.active.failed = true;
  }

  accept(event: PiEvent): SessionEventEnvelope[] {
    if (event.kind === "ready") return [];
    const turn = this.active;
    if (!turn || turn.requestId !== event.id) throw new Error("Pi event does not belong to admitted turn");
    const out: SessionEventEnvelope[] = [];
    switch (event.kind) {
      case "started":
      case "finished": // informational; only settlement ends admission
        break;
      case "text":
        if (turn.failed || !event.delta) break;
        if (!turn.textId) {
          turn.textId = turn.turnId + ":text:" + (this.seq + 1);
          out.push(this.envelope({type: "item_started", item: this.item("assistant_message", "in_progress")}, turn.textId));
        }
        out.push(this.envelope({type: "item_delta", delta: {appendText: event.delta}}, turn.textId));
        break;
      case "tool_started": {
        if (turn.failed) break;
        if (turn.seenTools.has(event.tool_id)) throw new Error("Duplicate Pi tool call");
        this.finishText(out);
        const itemId = turn.turnId + ":tool:" + (this.seq + 1);
        turn.seenTools.add(event.tool_id);
        turn.tools.set(event.tool_id, {itemId, name: event.name});
        out.push(this.envelope({type: "item_started",
          item: this.toolPayload(event.tool_id, event.name, "in_progress")}, itemId));
        break;
      }
      case "tool_finished": {
        if (turn.failed) break;
        const tool = turn.tools.get(event.tool_id);
        if (!tool || tool.name !== event.name) throw new Error("Unmatched Pi tool completion");
        turn.tools.delete(event.tool_id);
        out.push(this.envelope({type: "item_completed",
          item: this.toolPayload(event.tool_id, tool.name, event.error ? "failed" : "completed")}, tool.itemId));
        break;
      }
      case "job_submitted": // durable job association is held by history, not the transcript
        break;
      case "error":
      case "rejected":
        if (!turn.failed) this.fail(out, "PI_TURN_FAILED", "The Pi turn failed or was rejected. Inspect the workspace before retrying.");
        break;
      case "settled":
        if (!turn.failed && (turn.tools.size || turn.cancellationRequested)) {
          // v1 settlement has no confirmed stop reason. Do not synthesize
          // cancelled or successful status after a cancel request.
          this.fail(out, "PI_OUTCOME_UNCONFIRMED", "Turn settled without confirmed outcome; inspect scientific jobs.");
        }
        if (!turn.failed) {
          this.finishText(out);
          out.push(this.envelope({type: "turn_ended", stopReason: "end_turn"}));
        }
        this.active = null;
        break;
    }
    return out;
  }

  /** No successful turn or replay implied by loss of the native connection. */
  disconnect(): SessionEventEnvelope[] {
    if (!this.active) return [];
    const out: SessionEventEnvelope[] = [];
    if (!this.active.failed) this.fail(out, "PI_DISCONNECTED", "Pi connection interrupted; do not replay the operation automatically.");
    this.active = null;
    return out;
  }
}
