import { afterEach, describe, expect, it } from "vitest";
import type { PiHistorySession } from "../../../host/desktop-bridge";
import { createEmptySessionRecord, getSessionRecord, putSessionRecord, removeSessionRecord } from "#product/stores/sessions/session-records";
import { useSessionIntentStore } from "#product/stores/sessions/session-intent-store";
import { restorePiHistory } from "./history";
import { canSendPiSession } from "./product-session";

const sessionId = "a".repeat(32);
const turnId = "b".repeat(32);
const time = "2026-11-28T12:00:00.000Z";
const turn = { id: turnId, text: "Check the voltage.", timestamp: time, cancellationRequested: false };
const saved: PiHistorySession = {
  id: sessionId,
  modelId: "test-model",
  turns: [{
    ...turn,
    events: [{ kind: "text", id: turnId, delta: "Voltage checked." }, { kind: "settled", id: turnId }],
  }],
};

afterEach(() => removeSessionRecord(sessionId));

describe("Pi history restoration", () => {
  it("rebuilds settled history using the existing reducer without dispatching a prompt", () => {
    const outbox = useSessionIntentStore.getState().entriesById;
    expect(restorePiHistory("workspace", { sessions: [saved], skipped: 0 })).toBe(0);
    const restored = getSessionRecord(sessionId);
    expect(restored).toMatchObject({
      sessionId, workspaceId: "workspace", materializedSessionId: sessionId,
      transcriptHydrated: true, status: "idle", lastPromptAt: time,
      executionSummary: { hasLiveHandle: false },
    });
    expect(restored?.events.slice(-1)[0]?.event.type).toBe("turn_ended");
    expect(JSON.stringify(restored?.transcript)).toContain("Voltage checked.");
    expect(useSessionIntentStore.getState().entriesById).toBe(outbox);
    expect(canSendPiSession(sessionId, "workspace")).toBe(false);
    expect(restorePiHistory("another", { sessions: [saved], skipped: 0 })).toBe(0);
    expect(getSessionRecord(sessionId)?.workspaceId).toBe("workspace");
  });

  it("restores an interrupted turn as uncertain, leaving the composer read-only", () => {
    const interrupted = { ...saved, turns: [{ ...turn, events: [] }] };
    expect(restorePiHistory("workspace", { sessions: [interrupted], skipped: 0 })).toBe(0);
    const restored = getSessionRecord(sessionId);
    expect(restored?.status).toBe("errored");
    expect(restored?.events.slice(-1)[0]?.event).toMatchObject({ type: "error", code: "PI_DISCONNECTED" });
    expect(restored?.events.some(event => event.event.type === "turn_ended")).toBe(false);
    expect(canSendPiSession(sessionId, "workspace")).toBe(false);
  });

  it("treats settlement after an unconfirmed cancellation as uncertain", () => {
    const cancelled = { ...saved, turns: [{ ...saved.turns[0], cancellationRequested: true }] };
    expect(restorePiHistory("workspace", { sessions: [cancelled], skipped: 0 })).toBe(0);
    expect(getSessionRecord(sessionId)?.events.slice(-1)[0]?.event).toMatchObject({
      type: "error", code: "PI_OUTCOME_UNCONFIRMED",
    });
  });

  it("preserves an existing slot and reports malformed history", () => {
    const existing = createEmptySessionRecord(sessionId, "pi", { workspaceId: "workspace" });
    putSessionRecord(existing);
    expect(restorePiHistory("workspace", {
      sessions: [saved, { ...saved, id: "unreadable", turns: [{ ...turn, timestamp: "bad", events: [] }] }],
      skipped: 2,
    })).toBe(3);
    expect(getSessionRecord(sessionId)?.events).toHaveLength(0);
    expect(getSessionRecord("unreadable")).toBeNull();
  });
});
