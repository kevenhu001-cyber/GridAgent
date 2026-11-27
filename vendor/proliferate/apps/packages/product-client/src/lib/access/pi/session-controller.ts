import type { DesktopPiBridge, PiEvent } from "../../../host/desktop-bridge";

export type PiSessionStatus = "closed" | "opening" | "ready" | "sending" | "running" | "cancelling" | "failed";

export interface PiSessionSnapshot {
  status: PiSessionStatus;
  sessionId: string | null;
  requestId: string | null;
  failure: string | null;
}

type Listener = (snapshot: PiSessionSnapshot, events: readonly PiEvent[]) => void;
const delay = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms));

/** One controller owns one host session and its event reader.
 * No external Agent fallback; never retry an uncertain submission.
 * Product transcript integration consumes the event batches.
 */
export class PiSessionController {
  private snapshot: PiSessionSnapshot = {
    status: "closed", sessionId: null, requestId: null, failure: null,
  };
  private listeners = new Set<Listener>();
  private polling = false;
  private failedTurn = false;

  constructor(private readonly bridge: DesktopPiBridge) {}

  getSnapshot(): PiSessionSnapshot { return this.snapshot; }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  private publish(patch: Partial<PiSessionSnapshot>, events: readonly PiEvent[] = []) {
    this.snapshot = {...this.snapshot, ...patch};
    for (const listener of this.listeners) listener(this.snapshot, events);
  }

  async open() {
    if (this.snapshot.status !== "closed") throw new Error("Pi session is not closed");
    this.publish({status: "opening", failure: null});
    try {
      const sessionId = await this.bridge.open();
      this.publish({sessionId});
      const deadline = Date.now() + 30_000;
      while (this.snapshot.status === "opening") {
        await this.poll();
        if (this.getSnapshot().status !== "opening") break;
        if (Date.now() >= deadline) throw new Error("Pi startup timed out");
        await delay(50);
      }
      if (this.getSnapshot().status !== "ready") throw new Error("Pi did not become ready");
    } catch {
      const sessionId = this.snapshot.sessionId;
      if (sessionId) {
        try { await this.bridge.close(sessionId); } catch { /* no automatic recovery */ }
      }
      this.publish({status: "failed", failure: "Pi could not start", sessionId: null});
      throw new Error("Pi could not start");
    }
  }

  async prompt(text: string) {
    const {status, sessionId} = this.snapshot;
    if (status !== "ready" || !sessionId || this.polling) throw new Error("Pi session is not ready");
    if (!text.trim()) throw new Error("Prompt is empty");
    this.failedTurn = false;
    this.publish({status: "sending", failure: null});
    try {
      const requestId = await this.bridge.prompt(sessionId, text);
      this.publish({status: "running", requestId});
      return requestId;
    } catch {
      this.publish({status: "failed", failure: "Pi submission not confirmed; do not replay"});
      throw new Error("Pi submission not confirmed; do not replay");
    }
  }

  async cancel() {
    const {status, sessionId, requestId} = this.snapshot;
    if (status === "cancelling") return;
    if (status !== "running" || !sessionId || !requestId) throw new Error("No active Pi prompt");
    this.publish({status: "cancelling"});
    try {
      await this.bridge.abort(sessionId, requestId);
    } catch {
      if (this.snapshot.requestId !== requestId) return; // settlement won the race
      this.publish({status: "failed", failure: "Pi cancellation not confirmed"});
      throw new Error("Pi cancellation not confirmed");
    }
  }

  async poll(): Promise<readonly PiEvent[]> {
    const {status, sessionId} = this.snapshot;
    if (this.polling || !sessionId || !["opening", "running", "cancelling"].includes(status)) return [];
    this.polling = true;
    try {
      const events = await this.bridge.poll(sessionId);
      for (const event of events) {
        if (event.kind === "ready") {
          if (this.snapshot.status !== "opening") throw new Error("Unexpected Pi ready event");
          this.publish({status: "ready"}, [event]);
          continue;
        }
        if (event.id !== this.snapshot.requestId) throw new Error("Unmatched Pi request");
        if (event.kind === "error" || event.kind === "rejected") {
          this.failedTurn = true;
          this.publish({failure: "Pi prompt failed"}, [event]);
        } else if (event.kind === "settled") {
          this.publish({status: this.failedTurn ? "failed" : "ready", requestId: null}, [event]);
        } else {
          // "finished" is informational; the request remains busy until settled.
          this.publish({}, [event]);
        }
      }
      return events;
    } catch {
      this.publish({status: "failed", failure: "Pi event stream interrupted; do not replay"});
      throw new Error("Pi event stream interrupted; do not replay");
    } finally {
      this.polling = false;
    }
  }

  async close() {
    const {sessionId, status, requestId} = this.snapshot;
    if (this.polling || requestId || ["opening", "sending", "running", "cancelling"].includes(status)) {
      throw new Error("Wait for Pi settlement before closing");
    }
    if (sessionId) await this.bridge.close(sessionId);
    this.publish({status: "closed", sessionId: null, requestId: null, failure: null});
  }
}
