import { findLogicalWorkspace } from "#product/lib/domain/workspaces/cloud/logical-workspace-lookup";
import { getSessionRecord, getWorkspaceSessionRecords } from "#product/stores/sessions/session-records";
import { writeChatShellIntentForEmptySurface, writeChatShellIntentForSession } from "#product/hooks/workspaces/workflows/tabs/workspace-shell-intent-writer";
import { markWorkspaceViewed } from "#product/stores/preferences/workspace-ui-store";
import { useCallback } from "react";
import type { Workspace } from "@anyharness/sdk";
import { isNativeProjectId } from "@anyharness/sdk-react";
import { nativeProjectWorkspace } from "#product/lib/access/pi/native-project";
import { useProductHost } from "@proliferate/product-client/host/ProductHostProvider";
import { useWorkspaceBootstrapActions } from "#product/hooks/workspaces/workflows/use-workspace-bootstrap-actions";
import { useWorkspaceSelectionCache } from "#product/hooks/workspaces/cache/use-workspace-selection-cache";
import { buildLogicalWorkspaces } from "#product/lib/domain/workspaces/cloud/logical-workspaces";
import { buildStandardRepoProjection } from "#product/lib/domain/workspaces/cloud/standard-projection";
import { useHarnessConnectionStore } from "#product/stores/sessions/harness-connection-store";
import { useSessionDirectoryStore } from "#product/stores/sessions/session-directory-store";
import { useSessionSelectionStore } from "#product/stores/sessions/session-selection-store";
import { useSessionTranscriptStore } from "#product/stores/sessions/session-transcript-store";
import { clearWorkspaceRuntimeState } from "#product/hooks/workspaces/workflows/selection/clear-runtime-state";
import { runHotWorkspaceReopen } from "#product/hooks/workspaces/workflows/selection/run-hot-workspace-reopen";
import { runWorkspaceSelection } from "#product/hooks/workspaces/workflows/selection/run-workspace-selection";
import { restorePiHistory } from "#product/lib/access/pi/history";
import { useToastStore } from "#product/stores/toast/toast-store";

function removeWorkspaceSessionRecordsForWorkspace(workspaceId: string): void {
  const removedSessionIds =
    useSessionDirectoryStore.getState().removeWorkspaceEntries(workspaceId);
  useSessionTranscriptStore.getState().removeEntries(removedSessionIds);
}

export function useWorkspaceSelection() {
  const host = useProductHost();
  const desktop = host.desktop;
  const localRuntime = desktop?.runtime ?? null;
  const cloudClient = host.cloud.client;
  const {
    cancelPreviousWorkspaceDisplayQueries,
    getWorkspaceSelectionSnapshot,
  } = useWorkspaceSelectionCache();
  const setSelectedWorkspace = useSessionSelectionStore((state) => state.activateWorkspace);
  const clearSelection = useSessionSelectionStore((state) => state.clearSelection);
  const setSelectedLogicalWorkspaceId = useSessionSelectionStore(
    (state) => state.setSelectedLogicalWorkspaceId,
  );
  const { bootstrapWorkspace, reconcileHotWorkspace } = useWorkspaceBootstrapActions();

  return {
    selectWorkspace: useCallback(async (
      workspaceId: string,
      options?: {
        force?: boolean;
        forceCold?: boolean;
        forceSessionDirectoryRefresh?: boolean;
        preservePending?: boolean;
        initialActiveSessionId?: string | null;
        latencyFlowId?: string | null;
        knownWorkspace?: Workspace | null;
      },
    ) => {
      const runtimeUrl = useHarnessConnectionStore.getState().runtimeUrl;
      const {
        coworkStatus,
        workspaceCollections,
      } = getWorkspaceSelectionSnapshot(runtimeUrl);
      const standardProjection = workspaceCollections
        ? buildStandardRepoProjection({
          repoRoots: workspaceCollections.repoRoots,
          localWorkspaces: workspaceCollections.localWorkspaces,
          cloudWorkspaces: workspaceCollections.cloudWorkspaces,
          coworkRootRepoRootId: coworkStatus?.root?.repoRootId ?? null,
        })
        : null;
      const logicalWorkspaces = workspaceCollections
        ? buildLogicalWorkspaces({
          localWorkspaces: standardProjection?.localWorkspaces ?? [],
          repoRoots: standardProjection?.repoRoots ?? [],
          cloudWorkspaces: standardProjection?.cloudWorkspaces ?? [],
          currentSelectionId: useSessionSelectionStore.getState().selectedWorkspaceId,
        })
        : [];
      if (desktop?.pi) {
        const before=useSessionSelectionStore.getState();
        const native=await desktop.pi.mode();
        if (native) {
          const logical=findLogicalWorkspace(logicalWorkspaces,workspaceId);
          const targetId = logical?.localWorkspace?.id ?? workspaceId;
          let workspace=workspaceCollections?.localWorkspaces.find(w=>w.id===targetId);
          if (isNativeProjectId(targetId)) {
            if (!desktop.scientificProject) throw new Error("Native project discovery unavailable.");
            const identity = (await desktop.scientificProject.list()).find(project => project.id === targetId);
            if (!identity || !identity.available) throw new Error("Selected native project is no longer authorized or its folder is missing.");
            workspace = nativeProjectWorkspace(identity);
          }
          if (!workspace || workspace.surface!=="standard" || workspace.lifecycleState!=="active" ||
            workspace.availability==="workspace_directory_missing" || !await desktop.pi.matchesWorkspace(workspace.path))
            throw new Error("Choose a local workspace authorized for native Pi.");
          const history = await desktop.pi.history?.list(workspace.path).catch(() => null);
          const now=useSessionSelectionStore.getState();
          if(now.workspaceSelectionNonce!==before.workspaceSelectionNonce || now.activeSessionVersion!==before.activeSessionVersion) return;
          if (history && restorePiHistory(workspace.id, history) > 0) {
            useToastStore.getState().show("Some saved Pi sessions could not be read.");
          } else if (history === null) {
            useToastStore.getState().show("Pi session history is unavailable.");
          }
          if(now.selectedWorkspaceId===workspace.id && !options?.force) return;
          const requested=options?.initialActiveSessionId;
          const requestedSlot=requested ? getSessionRecord(requested) : null;
          const initial=options && "initialActiveSessionId" in options
            ? requestedSlot?.workspaceId===workspace.id && requestedSlot.agentKind==="pi" ? requestedSlot.sessionId : null
            : Object.values(getWorkspaceSessionRecords(workspace.id)).find(s=>s.agentKind==="pi" && s.status!=="closed")?.sessionId ?? null;
          cancelPreviousWorkspaceDisplayQueries({runtimeUrl,previousWorkspaceIds:[now.selectedLogicalWorkspaceId,now.selectedWorkspaceId],nextWorkspaceIds:[workspace.id]});
          setSelectedWorkspace({logicalWorkspaceId:isNativeProjectId(workspace.id) ? workspace.id : logical?.id ?? workspace.id,workspaceId:workspace.id,initialActiveSessionId:initial,hotPaintGate:null});
          if(initial) writeChatShellIntentForSession({workspaceId:workspace.id,sessionId:initial});
          else writeChatShellIntentForEmptySurface({workspaceId:workspace.id});
          markWorkspaceViewed(workspace.id);
          return;
        }
      }
      if (isNativeProjectId(workspaceId)) throw new Error("Native project mode is unavailable.");
      const deps = {
        localRuntime,
        cloudClient,
        cache: {
          cancelPreviousWorkspaceDisplayQueries,
        },
        logicalWorkspaces,
        rawWorkspaces: workspaceCollections?.localWorkspaces ?? [],
        setSelectedLogicalWorkspaceId,
        setSelectedWorkspace: (
          id: string,
          opts?: { initialActiveSessionId?: string | null },
        ) => setSelectedWorkspace({
          logicalWorkspaceId: useSessionSelectionStore.getState().selectedLogicalWorkspaceId,
          workspaceId: id,
          initialActiveSessionId: opts?.initialActiveSessionId,
        }),
        removeWorkspaceSlots: removeWorkspaceSessionRecordsForWorkspace,
        clearSelection,
        bootstrapWorkspace,
        reconcileHotWorkspace,
      };
      if (runHotWorkspaceReopen(deps, {
        workspaceId,
        options,
      })) {
        return;
      }
      await runWorkspaceSelection(deps, {
        workspaceId,
        options,
      });
    }, [
      bootstrapWorkspace,
      cancelPreviousWorkspaceDisplayQueries,
      clearSelection,
      getWorkspaceSelectionSnapshot,
      localRuntime,
      desktop?.pi,
      desktop?.scientificProject,
      reconcileHotWorkspace,
      setSelectedLogicalWorkspaceId,
      setSelectedWorkspace,
      cloudClient,
    ]),
    clearWorkspaceRuntimeState: useCallback((
      workspaceId: string,
      options?: { clearSelection?: boolean; clearDraftUiKey?: string | null },
    ) => {
      const currentSelectedWorkspaceId = useSessionSelectionStore.getState().selectedWorkspaceId;
      clearWorkspaceRuntimeState(
        {
          removeWorkspaceSlots: removeWorkspaceSessionRecordsForWorkspace,
          clearSelection,
        },
        workspaceId,
        options,
      );
      if (options?.clearSelection && currentSelectedWorkspaceId === workspaceId) {
        setSelectedLogicalWorkspaceId(null);
      }
    }, [clearSelection, setSelectedLogicalWorkspaceId]),
  };
}
