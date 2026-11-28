import type { Workspace } from "@anyharness/sdk";
import type { NativeScientificProjectIdentity } from "../../../host/desktop-bridge";

/** Reuse the workspace inventory contract without impersonating a Git repository.
 * Workspace.path is the Pi authorization root; file operations are relative to projectPath. */
export function nativeProjectWorkspace(identity: NativeScientificProjectIdentity): Workspace {
  if (!/^gridagent-scientific:[a-f0-9]{64}$/.test(identity.id) ||
      !identity.workspacePath.trim() || !identity.projectPath.trim()) {
    throw new Error("Invalid native scientific project identity.");
  }
  const label = identity.workspacePath.replace(/[\\/]+$/, "").split(/[\\/]/).pop() || "Scientific project";
  return {
    id: identity.id, kind: "local", repoRootId: identity.id,
    path: identity.workspacePath, displayName: label, surface: "standard",
    availability: "available", lifecycleState: "active",
    createdAt: "1970-01-01T00:00:00.000Z", updatedAt: "1970-01-01T00:00:00.000Z",
  };
}
