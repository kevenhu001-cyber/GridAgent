import { useMemo } from "react";
import { usePiModelSelector } from "#product/hooks/chat/derived/use-pi-model-selector";
import { canSendPiSession, hasOpenPiSession } from "#product/lib/access/pi/product-session";
import { useSessionDirectoryStore } from "#product/stores/sessions/session-directory-store";
import { selectPrimaryPendingInteraction } from "@anyharness/sdk";
import { useWorkspaces } from "#product/hooks/workspaces/cache/use-workspaces";
import { useSelectedCloudRuntimeState } from "#product/hooks/workspaces/facade/use-selected-cloud-runtime-state";
import { parseCloudWorkspaceSyntheticId } from "#product/lib/domain/workspaces/cloud/cloud-ids";
import { resolveCloudWorkspaceStatus } from "#product/lib/domain/workspaces/cloud/cloud-workspace-status";
import {
  resolveChatInputAvailability,
  type ChatInputAvailabilityState,
} from "#product/lib/domain/chat/composer/chat-input";
import { isWorkspaceDirectoryMissing } from "#product/lib/domain/workspaces/availability";
import { missingCheckoutCopy } from "#product/copy/workspaces/workspace-availability-copy";
import { useHarnessConnectionStore } from "#product/stores/sessions/harness-connection-store";
import { useSessionSelectionStore } from "#product/stores/sessions/session-selection-store";
import { useAttendedPendingWorkspaceEntry } from "#product/hooks/workspaces/derived/use-pending-workspace-entries";
import { useConfiguredLaunchReadiness } from "#product/hooks/chat/derived/use-configured-launch-readiness";
import { useSessionTranscriptStore } from "#product/stores/sessions/session-transcript-store";
import {
  resolveWorkspaceSessionRecoverySendBlockedReason,
} from "#product/lib/domain/workspaces/selection/session-recovery";
import type { ModelSelectorSelection } from "#product/lib/domain/chat/models/model-selector-types";

export type ChatAvailabilityState = ChatInputAvailabilityState;

// Owns read-only composer availability state. All disabling rules live in the
// pure chat-input resolver; this hook only gathers React state.
export function useChatAvailabilityState(options?: {
  activeSessionId?: string | null;
  activeLaunchSelection?: ModelSelectorSelection | null;
  launchReadiness?: {
    isLoading: boolean;
    isReady: boolean;
    disabledReason: string | null;
  };
}): ChatAvailabilityState {
  const native = usePiModelSelector();
  const piMode = native.mode;
  const selectedWorkspaceId = useSessionSelectionStore((state) => state.selectedWorkspaceId);
  const pendingWorkspaceEntry = useAttendedPendingWorkspaceEntry();
  const connectionState = useHarnessConnectionStore((state) => state.connectionState);
  const storedActiveSessionId = useSessionSelectionStore((state) => state.activeSessionId);
  const workspaceSessionRecovery = useSessionSelectionStore(
    (state) => state.workspaceSessionRecovery,
  );
  const activeSessionId = options && "activeSessionId" in options
    ? options.activeSessionId ?? null
    : storedActiveSessionId;
  const activeDirectory = useSessionDirectoryStore(state=>activeSessionId ? state.entriesById[activeSessionId] : null);
  const primaryPendingInteractionKind = useSessionTranscriptStore((state) => {
    const transcript = activeSessionId
      ? state.entriesById[activeSessionId]?.transcript ?? null
      : null;
    return transcript ? selectPrimaryPendingInteraction(transcript)?.kind ?? null : null;
  });
  const { data: workspaceCollections } = useWorkspaces();
  const selectedCloudRuntime = useSelectedCloudRuntimeState();
  const configuredLaunch = useConfiguredLaunchReadiness(options?.activeLaunchSelection ?? null);
  const launchReadiness = options?.launchReadiness ?? configuredLaunch;

  const selectedCloudWorkspaceId = parseCloudWorkspaceSyntheticId(selectedWorkspaceId);
  const selectedLocalWorkspace = selectedCloudWorkspaceId === null
    ? workspaceCollections?.workspaces.find((workspace) => workspace.id === selectedWorkspaceId)
      ?? null
    : null;
  const selectedCloudWorkspace =
    workspaceCollections?.cloudWorkspaces.find((workspace) => workspace.id === selectedCloudWorkspaceId)
    ?? null;
  const selectedCloudWorkspaceStatus = resolveCloudWorkspaceStatus(selectedCloudWorkspace);

  const availability = useMemo(() => resolveChatInputAvailability({
    selectedWorkspaceId,
    isCloudWorkspaceSelected: selectedCloudWorkspaceId !== null,
    workspaceDirectoryMissingSendReason:
      selectedLocalWorkspace && isWorkspaceDirectoryMissing(selectedLocalWorkspace)
        ? missingCheckoutCopy(selectedLocalWorkspace.kind).sendBlockedReason
        : null,
    connectionState,
    selectedCloudWorkspaceStatus,
    selectedCloudRuntimePhase: selectedCloudRuntime.state?.phase ?? null,
    selectedCloudRuntimeActionBlockReason: selectedCloudRuntime.state?.actionBlockReason ?? null,
    activeSessionId,
    isConfiguredLaunchLoading: launchReadiness.isLoading,
    hasReadyConfiguredLaunch: launchReadiness.isReady,
    configuredLaunchDisabledReason: launchReadiness.disabledReason,
    sessionRecoverySendReason:
      workspaceSessionRecovery?.sessionId === activeSessionId
        ? resolveWorkspaceSessionRecoverySendBlockedReason(
          workspaceSessionRecovery.reason,
        )
        : null,
    pendingWorkspaceEntry,
    pendingInteractionKind: primaryPendingInteractionKind,
  }), [
    activeSessionId,
    connectionState,
    launchReadiness.disabledReason,
    launchReadiness.isLoading,
    launchReadiness.isReady,
    pendingWorkspaceEntry,
    primaryPendingInteractionKind,
    selectedCloudRuntime.state?.actionBlockReason,
    selectedCloudRuntime.state?.phase,
    selectedCloudWorkspaceStatus,
    selectedLocalWorkspace,
    selectedWorkspaceId,
    selectedCloudWorkspaceId,
    workspaceSessionRecovery?.sessionId,
    workspaceSessionRecovery?.reason,
  ]);
  if (piMode !== "legacy") {
    const reason = piMode !== "native" ? "Native Pi runtime is unavailable or starting."
      : !selectedLocalWorkspace || pendingWorkspaceEntry ? "Select an existing local workspace for Pi."
      : isWorkspaceDirectoryMissing(selectedLocalWorkspace) ? missingCheckoutCopy(selectedLocalWorkspace.kind).sendBlockedReason
      : activeSessionId ? (activeDirectory?.agentKind==="pi" && canSendPiSession(activeSessionId,selectedLocalWorkspace.id)
        ? null : "This session is read-only. Start a native Pi chat.")
      : hasOpenPiSession() ? "Close the current native Pi session before starting another."
      : !native.selection ? "Choose a model with a configured API key."
      : null;
    return {...availability,isDisabled:false,disabledReason:null,sendBlockedReason:reason,
      areRuntimeControlsDisabled:piMode!=="native"};
  }
  return availability;
}
