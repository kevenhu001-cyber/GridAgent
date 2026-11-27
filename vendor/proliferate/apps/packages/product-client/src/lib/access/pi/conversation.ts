import type { DesktopPiBridge } from "../../../host/desktop-bridge";
import type { PiSessionSnapshot } from "./session-controller";
import { PiSessionController } from "./session-controller";

import { applyPiEvent, settlePiTurn, type PiTurn } from "./conversation-events";

export interface PiConversationSnapshot {session: PiSessionSnapshot; turns: PiTurn[]}

export class PiConversation {
  readonly workspacePath: string;
  private controller: PiSessionController;
  private snapshot: PiConversationSnapshot;
  private listeners = new Set<() => void>();
  private sending = false;
  private cancelling = false;
  private nextId = 0;
  constructor(bridge: DesktopPiBridge, workspacePath: string) {
    this.workspacePath = workspacePath;
    this.controller = new PiSessionController(bridge);
    this.snapshot = {session: this.controller.getSnapshot(), turns: []};
    this.controller.subscribe((session, events) => {
      let turns = this.snapshot.turns;
      const last = turns.at(-1);
      if (last?.status === "running") {
        let turn = last;
        for (const event of events) turn = applyPiEvent(turn, event);
        if (session.status === "failed" || events.some(e => e.kind === "settled")) {
          const status = session.status === "failed" ? "failed" : this.cancelling ? "cancel_requested" : "complete";
          turn = settlePiTurn(turn, status);
        }
        turns = [...turns.slice(0, -1), turn];
      }
      this.publish({session, turns});
    });
  }

  getSnapshot = () => this.snapshot;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {this.listeners.delete(listener);};
  };
  private publish(snapshot: PiConversationSnapshot) {
    this.snapshot = snapshot;
    this.listeners.forEach(listener => listener());
  }

  async send(prompt: string) {
    if (this.sending || !prompt.trim() || !["closed","ready"].includes(this.snapshot.session.status))
      throw new Error("Pi conversation is unavailable");
    this.sending = true;
    this.cancelling = false;
    this.publish({...this.snapshot, turns: [...this.snapshot.turns,
      {id: ++this.nextId, prompt, segments: [], status: "running"}]});
    try {
      if (this.controller.getSnapshot().status === "closed") await this.controller.open(this.workspacePath);
      await this.controller.prompt(prompt);
      await this.controller.drainTurn();
    } finally {this.sending = false;}
  }

  async cancel() {
    if (this.snapshot.session.status !== "running") return;
    this.cancelling = true;
    await this.controller.cancel();
  }

  async newChat() {
    if (this.sending || this.snapshot.session.status !== "ready") throw new Error("Pi is busy");
    this.sending = true;
    try {
      await this.controller.close();
      this.publish({...this.snapshot, turns: []});
    } finally {this.sending = false;}
  }
}
