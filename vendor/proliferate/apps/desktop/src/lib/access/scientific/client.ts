import { invoke } from "@tauri-apps/api/core";

export type ScientificReadMethod =
  | "hello" | "scientific.status" | "scientific.runs" | "scientific.artifact"
  | "solver.backends" | "solver.table" | "workspace.files";

type ScientificResponse<T> =
  | { version: 1; id: string; ok: true; result: T }
  | { version: 1; id: string; ok: false; error: { code: string } };

/** Direct first-party host call, independent of the external MCP registry. */
export async function scientificRead<T>(
  method: ScientificReadMethod,
  params: Record<string, unknown> = {},
): Promise<T> {
  const response = await invoke<ScientificResponse<T>>("scientific_read", { method, params });
  if (response.version !== 1) throw new Error("Scientific protocol version mismatch");
  if (!response.ok) throw new Error(response.error.code);
  return response.result;
}

export interface ScientificEnvironment {
  status: string;
  enabled: boolean;
  sandbox_available: boolean;
  execution_blocked_by_session: boolean;
  active_run_id: string | null;
  backend: string;
  timeout_seconds: number;
  max_plugins_per_run: number;
}

export function getScientificEnvironment() {
  return scientificRead<ScientificEnvironment>("scientific.status");
}
