import { invoke } from "@tauri-apps/api/core";
import type { NativeProjectFiles } from "@anyharness/sdk-react";
import type { StatWorkspaceFileResponse, ListWorkspaceFilesResponse, SearchWorkspaceFilesResponse, ReadWorkspaceFileResponse, WriteWorkspaceFileRequest, WriteWorkspaceFileResponse } from "@anyharness/sdk";

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
export interface ScientificProjectIdentity {
  id: string;
  workspacePath: string;
  projectPath: string;
}

export function getScientificProjectIdentity() {
  return invoke<ScientificProjectIdentity>("scientific_project_identity");
}

async function projectRead<T>(
  projectId: string, method: "workspace.tree" | "workspace.search" | "workspace.inspect" | "workspace.read",
  params: Record<string, unknown>,
): Promise<T> {
  const response = await invoke<ScientificResponse<T>>("scientific_project_read", { projectId, method, params });
  if (response.version !== 1) throw new Error("Scientific protocol version mismatch");
  if (!response.ok) throw new Error(response.error.code);
  return response.result;
}

export function listScientificDirectory(projectId: string, path = "") {
  return projectRead<ListWorkspaceFilesResponse>(projectId, "workspace.tree", { path });
}

export function searchScientificFiles(projectId: string, query: string, limit = 25) {
  return projectRead<SearchWorkspaceFilesResponse>(projectId, "workspace.search", { query, limit });
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
export async function readScientificProjectFile(projectId: string, path: string): Promise<ReadWorkspaceFileResponse> {
  const meta = await projectRead<ProjectMetadata>(projectId, "workspace.inspect", { path });
  if (meta.path !== path) throw new Error("Scientific file identity mismatch");
  let content: string | null = null;
  if (meta.text_readable) {
    let offset = 0;
    const chunks: string[] = [];
    for (let count = 0; count < 90; count++) {
      const page = await projectRead<ProjectPage>(projectId, "workspace.read", { path, offset });
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


/** Existing-file save uses the same native project identity as reads and the
 * editor's observed revision. Never route to a legacy repository on failure. */
export async function saveScientificProjectFile(
  projectId: string, input: WriteWorkspaceFileRequest,
): Promise<WriteWorkspaceFileResponse> {
  const response = await invoke<ScientificResponse<{path: string; sha256: string; size_bytes: number}>>(
    "scientific_project_write", {
      projectId, path: input.path, text: input.content, expectedSha256: input.expectedVersionToken,
    },
  );
  if (response.version !== 1) throw new Error("Scientific protocol version mismatch");
  if (!response.ok) throw new Error(response.error.code);
  if (response.result.path !== input.path) throw new Error("Scientific file identity mismatch");
  return {path: response.result.path, versionToken: response.result.sha256, sizeBytes: response.result.size_bytes};
}


/** Stat the root/directories without trying to decode a directory as a file. */
export async function statScientificProjectFile(id: string, path: string): Promise<StatWorkspaceFileResponse> {
  if (path === "") {
    await listScientificDirectory(id, "");
    return {path: "", kind: "directory"};
  }
  const parent = path.slice(0, Math.max(0, path.lastIndexOf("/")));
  const entry = (await listScientificDirectory(id, parent)).entries.find(row => row.path === path);
  if (!entry) throw new Error("Scientific project entry unavailable");
  if (entry.kind === "directory") return {path, kind: "directory"};
  const meta = await projectRead<ProjectMetadata>(id, "workspace.inspect", {path});
  if (meta.path !== path) throw new Error("Scientific file identity mismatch");
  return {path, kind: "file", sizeBytes: meta.size_bytes, isText: meta.text_readable};
}

export const nativeScientificFiles: NativeProjectFiles = {
  list: listScientificDirectory,
  search: searchScientificFiles,
  read: readScientificProjectFile,
  stat: statScientificProjectFile,
  write: saveScientificProjectFile,
};
