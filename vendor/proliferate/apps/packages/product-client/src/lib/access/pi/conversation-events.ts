import type { PiEvent } from "../../../host/desktop-bridge";

type Segment = {kind: "text"; text: string} |
  {kind: "tool"; id: string; name: string; status: "running" | "ok" | "error" | "interrupted"};
export type TurnStatus = "running" | "complete" | "failed" | "cancel_requested";
export interface PiTurn {id: number; prompt: string; segments: Segment[]; status: TurnStatus}

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

/** Finalize unfinished tools without falsely marking them successful. */
export function settlePiTurn(turn: PiTurn, status: Exclude<TurnStatus, "running">): PiTurn {
  return {...turn, status, segments: turn.segments.map(s =>
    s.kind === "tool" && s.status === "running" ? {...s, status: "interrupted"} : s)};
}
