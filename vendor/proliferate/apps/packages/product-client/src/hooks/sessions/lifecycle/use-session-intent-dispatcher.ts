import { useCallback, useEffect, useReducer, useRef } from "react";
import { dispatchPiPromptIntent, isPiProductSession } from "#product/lib/access/pi/product-session";
import { useProductHost } from "@proliferate/product-client/host/ProductHostProvider";
import {
  useDeletePendingPromptMutation,
  useEditPendingPromptMutation,
  usePromptSessionMutation,
  useResolveSessionInteractionMutation,
  useSetSessionConfigOptionMutation,
} from "@anyharness/sdk-react";
import {
  selectNextDispatchableSessionIntent,
} from "#product/domain/sessions/intents/session-intent-selectors";
import type {
  SessionIntent,
} from "#product/domain/sessions/intents/session-intent-model";
import { useSessionHistoryHydration } from "#product/hooks/sessions/lifecycle/use-session-history-hydration";
import { useSessionSummaryActions } from "#product/hooks/sessions/workflows/use-session-summary-actions";
import { useSessionTitleActions } from "#product/hooks/sessions/workflows/use-session-title-actions";
import { useWorkspaceNameActions } from "#product/hooks/workspaces/workflows/use-workspace-name-actions";
import { useWorkspaceSurfaceLookup } from "#product/hooks/workspaces/derived/use-workspace-surface-lookup";
import { useWorkspaceSessionCache } from "#product/hooks/access/anyharness/sessions/use-workspace-session-cache";
import { getSessionRecord } from "#product/stores/sessions/session-records";
import { useSessionIntentStore } from "#product/stores/sessions/session-intent-store";
import { logLatency } from "#product/lib/infra/measurement/measurement-port";
import { useToastStore } from "#product/stores/toast/toast-store";
import {
  dispatchConfigIntent,
} from "#product/hooks/sessions/lifecycle/session-intent-config-dispatch";
import {
  dispatchDeletePendingPromptIntent,
  dispatchEditPendingPromptIntent,
  dispatchInteractionIntent,
} from "#product/hooks/sessions/lifecycle/session-intent-interaction-dispatch";
import {
  dispatchPromptIntent,
} from "#product/hooks/sessions/lifecycle/session-intent-prompt-dispatch";

let activeDispatcherOwner: symbol | null = null;

export function useSessionIntentDispatcher(): void {
  const host = useProductHost();
  const cloudClient = host.cloud.client;
  const dispatchVersion = useSessionIntentStore((state) => state.dispatchVersion);
  const { rehydrateSessionSlotFromHistory } = useSessionHistoryHydration();
  const { applySessionSummary } = useSessionSummaryActions();
  const { maybeGenerateSessionTitle } = useSessionTitleActions();
  const { maybeGenerateWorkspaceName } = useWorkspaceNameActions();
  const { getWorkspaceSurface } = useWorkspaceSurfaceLookup();
  const { upsertWorkspaceSessionRecord } = useWorkspaceSessionCache();
  const showErrorToast = useToastStore((state) => state.showError);
  const promptSessionMutation = usePromptSessionMutation();
  const setSessionConfigOptionMutation = useSetSessionConfigOptionMutation();
  const resolveInteractionMutation = useResolveSessionInteractionMutation();
  const editPendingPromptMutation = useEditPendingPromptMutation();
  const deletePendingPromptMutation = useDeletePendingPromptMutation();
  const inFlightSessionIdsRef = useRef(new Set<string>());
  const dispatcherOwnerRef = useRef<symbol | null>(null);
  const [dispatchSettlementVersion, notifyDispatchSettled] = useReducer(
    (version: number) => version + 1,
    0,
  );

  useEffect(() => {
    if (activeDispatcherOwner) {
      return;
    }
    const owner = Symbol("session-intent-dispatcher");
    activeDispatcherOwner = owner;
    dispatcherOwnerRef.current = owner;
    return () => {
      if (activeDispatcherOwner === owner) {
        activeDispatcherOwner = null;
      }
      dispatcherOwnerRef.current = null;
    };
  }, []);

  const dispatchIntent = useCallback(async function dispatchIntent(intent: SessionIntent) {
    if (isPiProductSession(intent.clientSessionId)) {
      if (intent.kind === "send_prompt") await dispatchPiPromptIntent(intent);
      else useSessionIntentStore.getState().patchIntent(intent.intentId,{status:"failed",errorMessage:"This operation is not supported by native Pi yet."});
      return;
    }
    // Unknown/native mode must not dispatch old Agent intents.
    if (host.desktop?.pi) {
      let legacy=false;
      try {legacy=!(await host.desktop.pi.mode());} catch { /* fail closed */ }
      if (!legacy) {
        useSessionIntentStore.getState().patchIntent(intent.intentId,intent.kind==="send_prompt"
          ? {status:"failed",deliveryState:"failed_before_dispatch",errorMessage:"External Agent dispatch is disabled in native Pi mode."}
          : {status:"failed",errorMessage:"External Agent dispatch is disabled in native Pi mode."});
        return;
      }
    }
    switch (intent.kind) {
      case "send_prompt":
        await dispatchPromptIntent(intent, {
          applySessionSummary,
          maybeGenerateSessionTitle,
          maybeGenerateWorkspaceName,
          promptSessionMutation,
          rehydrateSessionSlotFromHistory,
          cloudClient,
          upsertWorkspaceSessionRecord,
        });
        break;
      case "update_config":
        await dispatchConfigIntent(intent, {
          getWorkspaceSurface,
          setSessionConfigOptionMutation,
          cloudClient,
          upsertWorkspaceSessionRecord,
          onFailure: (message) => {
            // Names the setting and the value the user chose: this fires from a
            // control whose menu has already closed, so the toast is the only
            // thing left that can say which change did not take.
            showErrorToast({
              headline: "Setting not changed",
              consequence: `${intent.controlKey} is still on its previous value, not ${intent.value}.`,
              cause: message,
              retry: () => void dispatchIntent(intent),
            });
          },
        });
        break;
      case "resolve_interaction":
        await dispatchInteractionIntent(intent, { resolveInteractionMutation, cloudClient });
        break;
      case "edit_pending_prompt":
        await dispatchEditPendingPromptIntent(intent, { editPendingPromptMutation, cloudClient });
        break;
      case "delete_pending_prompt":
        await dispatchDeletePendingPromptIntent(intent, { deletePendingPromptMutation, cloudClient });
        break;
    }
  }, [
    applySessionSummary,
    deletePendingPromptMutation,
    editPendingPromptMutation,
    getWorkspaceSurface,
    maybeGenerateSessionTitle,
    maybeGenerateWorkspaceName,
    promptSessionMutation,
    rehydrateSessionSlotFromHistory,
    resolveInteractionMutation,
    setSessionConfigOptionMutation,
    showErrorToast,
    cloudClient,
    host.desktop?.pi,
    upsertWorkspaceSessionRecord,
  ]);

  useEffect(() => {
    if (!isActiveDispatcherOwner(dispatcherOwnerRef.current)) {
      return;
    }

    const state = useSessionIntentStore.getState();
    for (const clientSessionId of Object.keys(state.intentIdsByClientSessionId)) {
      if (inFlightSessionIdsRef.current.has(clientSessionId)) {
        continue;
      }
      const intent = selectNextDispatchableSessionIntent(state, clientSessionId);
      if (!intent) {
        continue;
      }
      const record = getSessionRecord(clientSessionId);
      if (!record?.materializedSessionId) {
        logLatency("session.intent.dispatch.waiting_unmaterialized", {
          clientSessionId,
          nextIntentId: intent.intentId,
          nextIntentKind: intent.kind,
          hasRecord: Boolean(record),
          workspaceId: record?.workspaceId ?? intent.workspaceId,
          status: record?.status ?? null,
          transcriptHydrated: record?.transcriptHydrated ?? null,
          intentWorkspaceId: intent.workspaceId,
          intentCount: state.intentIdsByClientSessionId[clientSessionId]?.length ?? 0,
        });
        continue;
      }
      inFlightSessionIdsRef.current.add(clientSessionId);
      void dispatchIntent(intent).finally(() => {
        inFlightSessionIdsRef.current.delete(clientSessionId);
        if (isActiveDispatcherOwner(dispatcherOwnerRef.current)) {
          notifyDispatchSettled();
        }
      });
    }
  }, [dispatchIntent, dispatchSettlementVersion, dispatchVersion]);
}

function isActiveDispatcherOwner(owner: symbol | null): boolean {
  return owner !== null && activeDispatcherOwner === owner;
}
