import { invoke } from "@tauri-apps/api/core";

export type PiEvent =
  | { kind: "ready"; version: 1 }
  | { kind: "started" | "finished" | "settled" | "rejected"; id: string }
  | { kind: "text"; id: string; delta: string }
  | { kind: "error"; id: string; code: "provider_error" | "agent_failure" }
  | { kind: "tool_started"; id: string; tool_id: string; name: string }
  | { kind: "tool_finished"; id: string; tool_id: string; name: string; error: boolean };

/** Debug bridge only; callers supply neither credentials nor executable paths.
 * Open once, poll for ready, then prompt. Continue polling until settled,
 * even after abort or finished. Never automatically replay on disconnect.
 */
export const embeddedPi = {
  open: () => invoke<void>("pi_open"),
  prompt: (text: string) => invoke<string>("pi_prompt", { text }),
  abort: (id: string) => invoke<void>("pi_abort", { id }),
  poll: () => invoke<PiEvent[]>("pi_poll"),
  close: () => invoke<void>("pi_close"),
};
