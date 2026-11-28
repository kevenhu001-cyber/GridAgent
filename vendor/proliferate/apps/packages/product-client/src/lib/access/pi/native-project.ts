import type { Workspace } from "@anyharness/sdk";
import type { NativeScientificProjectIdentity } from "../../../host/desktop-bridge";

/** Reuse the workspace inventory contract without impersonating a Git repository.
 * Workspace.path is the Pi authorization root; file operations are relative to projectPath. */
export function nativeProjectWorkspace(identity: NativeScientificProjectIdentity): Workspace {
  if (!/^gridagent-scientific:[a-f0-9]{64}$/.test(identity.id) ||
      !identity.workspacePath.trim() || !identity.projectPath.trim() ||
      typeof identity.available !== "boolean" || !identity.createdAt.trim()) {
    throw new Error("Invalid native scientific project identity.");
  }
  const label = identity.workspacePath.replace(/[\\/]+$/, "").split(/[\\/]/).pop() || "Scientific project";
  return {
    id: identity.id, kind: "local", repoRootId: identity.id,
    path: identity.workspacePath, displayName: label, surface: "standard",
    availability: identity.available ? "available" : "workspace_directory_missing", lifecycleState: "active",
    createdAt: identity.createdAt, updatedAt: identity.createdAt,
  };
}
