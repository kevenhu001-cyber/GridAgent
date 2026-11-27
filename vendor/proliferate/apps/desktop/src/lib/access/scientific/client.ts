import { invoke } from "@tauri-apps/api/core";

export type ScientificReadMethod =
  | "hello" | "scientific.status" | "scientific.runs" | "scientific.artifact"
  | "solver.backends" | "solver.table" | "workspace.files" | "workspace.read" | "job.status";

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

export interface ScientificJob {
  job_id: string;
  status: "queued" | "running" | "ok" | "failed" | "cancelled" | "timeout"
    | "cleanup_unconfirmed" | "recovered_incomplete";
  cancellation_requested: boolean;
  reason?: string | null;
  run_id?: string | null;
  verification?: string | null;
}

async function scientificTask<T>(
  method: "workspace.write" | "job.submit" | "job.cancel",
  params: Record<string, unknown>,
): Promise<T> {
  const response = await invoke<ScientificResponse<T>>("scientific_task", { method, params });
  if (response.version !== 1) throw new Error("Scientific protocol version mismatch");
  if (!response.ok) throw new Error(response.error.code);
  return response.result;
}

/** Allocate the ID once per deliberate submission; use the same ID to resolve uncertainty. */
export function submitScientificJob(jobId: string, entry: string, args: string[] = [], pluginIds: string[] = []) {
  return scientificTask<ScientificJob>("job.submit", {
    job_id: jobId, entry, arguments: args, plugin_ids: pluginIds,
  });
}

export function getScientificJob(jobId: string) {
  return scientificRead<ScientificJob>("job.status", { job_id: jobId });
}

export function cancelScientificJob(jobId: string) {
  return scientificTask<ScientificJob>("job.cancel", { job_id: jobId });
}

export function writeScientificFile(path: string, text: string, expectedSha256: string | null = null) {
  return scientificTask<{ status: string; path: string; sha256: string; size_bytes: number }>(
    "workspace.write", { path, text, expected_sha256: expectedSha256 },
  );
}
