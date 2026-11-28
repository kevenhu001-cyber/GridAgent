import type { SessionEventEnvelope } from "@anyharness/sdk";
import type { PiHistory } from "../../../host/desktop-bridge";
import { replaySessionHistory } from "#product/lib/domain/sessions/stream/stream-state";
import { createEmptySessionRecord, getSessionRecord, putSessionRecord } from "#product/stores/sessions/session-records";
import { PiEventAdapter } from "./event-adapter";
import { PI_AGENT_KIND, ownsPiSession } from "./product-session";

/** Hydrate the existing transcript without opening a worker or dispatching a turn. */
export function restorePiHistory(workspaceId: string, history: PiHistory): number {
  let skipped = history.skipped;
  for (const session of history.sessions) {
    if (getSessionRecord(session.id) || ownsPiSession(session.id)) continue;
    try {
      let timestamp = "";
      const adapter = new PiEventAdapter(session.id, 0, () => timestamp);
      const envelopes: SessionEventEnvelope[] = [];
      for (const turn of session.turns) {
        timestamp = new Date(turn.timestamp).toISOString();
        // The durable request ID is only a transcript identity here. The
        // live transport still reconciles the original outbox prompt ID.
        envelopes.push(...adapter.begin(turn.id, turn.id, turn.text, turn.jobs ?? []));
        if (turn.cancellationRequested) adapter.noteCancellation(turn.id);
        for (const event of turn.events) envelopes.push(...adapter.accept(event));
        envelopes.push(...adapter.disconnect());
      }
      const last = envelopes[envelopes.length - 1];
      if (!last) continue;
      const interrupted = last.event.type === "error";
      const record = createEmptySessionRecord(session.id, PI_AGENT_KIND, {
        workspaceId,
        modelId: session.modelId,
        materializedSessionId: session.id,
        sessionRelationship: { kind: "root" },
      });
      const state = replaySessionHistory(session.id, envelopes);
      putSessionRecord({
        ...record,
        ...state,
        status: interrupted ? "errored" : "idle",
        executionSummary: {
          phase: interrupted ? "errored" : "idle",
          hasLiveHandle: false,
          pendingInteractions: [],
          updatedAt: last.timestamp,
        },
        transcriptHydrated: true,
        streamConnectionState: "ended",
        hasAttemptedPrompt: true,
        lastPromptAt: last.timestamp,
        piResume: !interrupted && session.resumeRevision && session.provider
          ? { revision: session.resumeRevision, provider: session.provider }
          : null,
      });
    } catch {
      skipped++;
    }
  }
  return skipped;
}
