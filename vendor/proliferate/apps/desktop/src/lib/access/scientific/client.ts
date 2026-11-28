import { invoke } from "@tauri-apps/api/core";
import type { ListWorkspaceFilesResponse, SearchWorkspaceFilesResponse, ReadWorkspaceFileResponse } from "@anyharness/sdk";

export type ScientificReadMethod =
  | "hello" | "scientific.status" | "scientific.runs" | "scientific.artifact"
  | "solver.backends" | "solver.table" | "workspace.files" | "workspace.read" | "job.status"
  | "workspace.tree" | "workspace.search" | "workspace.inspect";

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


/** Native scientific-project file transport primitives. No caller-supplied root or
 * AnyHarness process is needed. Consumers must bind these to an authorized
 * workspace before replacing the retained file tree's current transport. */
export function listScientificDirectory(path = "") {
  return scientificRead<ListWorkspaceFilesResponse>("workspace.tree", { path });
}

export function searchScientificFiles(query: string, limit = 25) {
  return scientificRead<SearchWorkspaceFilesResponse>("workspace.search", { query, limit });
}

interface ProjectMetadata {
  path: string;
  sha256: string;
  size_bytes: number;
  text_readable: boolean;
}

interface ProjectPage {
  path: string;
  sha256: string;
  text: string;
  next_offset: number | null;
}

/** Reuse the existing read response contract and revision guard. Binary files
 * get metadata only. Each page must belong to the same content revision. */
export async function readScientificProjectFile(path: string): Promise<ReadWorkspaceFileResponse> {
  const meta = await scientificRead<ProjectMetadata>("workspace.inspect", { path });
  let content: string | null = null;
  if (meta.text_readable) {
    let offset = 0;
    const chunks: string[] = [];
    for (let count = 0; count < 90; count++) {
      const page = await scientificRead<ProjectPage>("workspace.read", { path, offset });
      if (page.path !== path || page.sha256 !== meta.sha256) {
        throw new Error("Scientific file changed while reading");
      }
      chunks.push(page.text);
      if (page.next_offset === null) {
        content = chunks.join("");
        break;
      }
      if (!Number.isSafeInteger(page.next_offset) || page.next_offset <= offset) {
        throw new Error("Invalid scientific file pagination");
      }
      offset = page.next_offset;
    }
    if (content === null || new TextEncoder().encode(content).length !== meta.size_bytes) {
      throw new Error("Incomplete scientific file read");
    }
  }
  return {
    path: meta.path, kind: "file", content, versionToken: meta.sha256,
    encoding: meta.text_readable ? "utf-8" : null, sizeBytes: meta.size_bytes,
    isText: meta.text_readable, tooLarge: false,
  };
}
