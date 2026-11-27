import type { DesktopPiBridge, PiEvent } from "../../../host/desktop-bridge";
import type { PiSessionSnapshot } from "./session-controller";
import { PiSessionController } from "./session-controller";

type Segment = {kind: "text"; text: string} |
  {kind: "tool"; id: string; name: string; status: "running" | "ok" | "error" | "interrupted"};
type TurnStatus = "running" | "complete" | "failed" | "cancelled";
export interface PiTurn {id: number; prompt: string; segments: Segment[]; status: TurnStatus}
export interface PiConversationSnapshot {session: PiSessionSnapshot; turns: PiTurn[]}

/** Public event projection only. No raw tool arguments, reasoning or outputs. */
export function applyPiEvent(turn: PiTurn, event: PiEvent): PiTurn {
  if (event.kind === "text") {
    const last = turn.segments.at(-1);
    const segments = last?.kind === "text"
      ? [...turn.segments.slice(0, -1), {kind: "text" as const, text: last.text + event.delta}]
      : [...turn.segments, {kind: "text" as const, text: event.delta}];
    return {...turn, segments};
  }
  if (event.kind === "tool_started" && !turn.segments.some(s => s.kind === "tool" && s.id === event.tool_id)) {
    return {...turn, segments: [...turn.segments, {kind: "tool", id: event.tool_id, name: event.name, status: "running"}]};
  }
  if (event.kind === "tool_finished") return {...turn, segments: turn.segments.map(s =>
    s.kind === "tool" && s.id === event.tool_id ? {...s, status: event.error ? "error" : "ok"} : s)};
  return turn;
}

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
          const status = session.status === "failed" ? "failed" : this.cancelling ? "cancelled" : "complete";
          turn = {...turn, status, segments: turn.segments.map(s =>
            s.kind === "tool" && s.status === "running" ? {...s, status: "interrupted"} : s)};
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
