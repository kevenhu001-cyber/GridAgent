import { useEffect, useState, type ReactNode } from "react";
import type { DesktopPiBridge } from "@proliferate/product-client/host/desktop-bridge";
import type { WorkspaceRenderSurface } from "#product/lib/domain/workspaces/tabs/shell-activation";
import { useSessionSelectionStore } from "#product/stores/sessions/session-selection-store";
import { useWorkspaces } from "#product/hooks/workspaces/cache/use-workspaces";
import { NativePiChat } from "./NativePiChat";

function Notice({children}: {children: ReactNode}) {
  return <div className="flex min-h-0 flex-1 items-center justify-center p-8 text-center text-chat text-muted-foreground" role="status">{children}</div>;
}

export function NativePiChatGate({bridge, surface, children}: {
  bridge: DesktopPiBridge;
  surface?: WorkspaceRenderSurface | null;
  children: ReactNode;
}) {
  const [mode, setMode] = useState<"checking" | "native" | "legacy" | "failed">("checking");
  useEffect(() => {
    let live = true;
    void bridge.mode().then(enabled => {
      if (live) setMode(enabled ? "native" : "legacy");
    }, () => { if (live) setMode("failed"); });
    return () => {live = false;};
  }, [bridge]);
  if (mode === "legacy") return <>{children}</>;
  if (mode === "checking") return <Notice>Checking local Agent runtime…</Notice>;
  if (mode === "failed") return <Notice>Could not verify the local Agent runtime. No Agent was started.</Notice>;
  if (surface?.kind === "chat-session" || surface?.kind === "chat-session-pending")
    return <Notice>Legacy sessions are not writable in GridAgent Pi preview. Open the workspace chat shell.</Notice>;
  return <WorkspaceGate bridge={bridge} />;
}

function WorkspaceGate({bridge}: {bridge: DesktopPiBridge}) {
  const workspaceId = useSessionSelectionStore(state => state.selectedWorkspaceId);
  const {data} = useWorkspaces();
  const path = data?.localWorkspaces.find(workspace => workspace.id === workspaceId)?.path ?? null;
  const [checked, setChecked] = useState<{path: string; match: boolean} | null>(null);
  useEffect(() => {
    let live = true;
    if (path) void bridge.matchesWorkspace(path).then(match => {
      if (live) setChecked({path, match});
    }, () => {if (live) setChecked({path, match: false});});
    return () => {live = false;};
  }, [bridge, path]);
  if (!path) return <Notice>Select the configured local scientific workspace to start GridAgent.</Notice>;
  if (checked?.path !== path) return <Notice>Checking scientific workspace…</Notice>;
  if (!checked.match) return <Notice>This workspace is not the configured GridAgent scientific workspace.</Notice>;
  return <NativePiChat bridge={bridge} workspacePath={path} />;
}
