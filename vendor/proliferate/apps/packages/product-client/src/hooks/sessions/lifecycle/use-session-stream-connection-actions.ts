import { useCallback } from "react";
import { isPiProductSession } from "#product/lib/access/pi/product-session";
import { useProductHost } from "@proliferate/product-client/host/ProductHostProvider";
import { openSessionStreamConnection } from "#product/hooks/sessions/lifecycle/session-stream-connection-open";
import { prepareSessionStreamConnection } from "#product/hooks/sessions/lifecycle/session-stream-connection-prepare";
import { closeSessionSlotStream as closeSessionSlotStreamForSession } from "#product/hooks/sessions/lifecycle/session-stream-slot-connection";
import type {
  SessionStreamConnectOptions,
  UseSessionStreamConnectionActionsOptions,
} from "#product/hooks/sessions/lifecycle/session-stream-connection-types";

export function useSessionStreamConnectionActions({
  createSessionStreamFlushController,
  refreshSessionSlotMeta,
  rehydrateSessionSlotFromHistory,
}: UseSessionStreamConnectionActionsOptions) {
  const host = useProductHost();
  const cloudClient = host.cloud.client;
  const closeSessionSlotStream = useCallback((sessionId: string) => {
    closeSessionSlotStreamForSession(sessionId);
  }, []);

  const ensureSessionStreamConnected = useCallback(async (
    sessionId: string,
    options?: SessionStreamConnectOptions,
  ): Promise<void> => {
    // Native transport owns its reader; never attach AnyHarness SSE to a Pi session.
    if (isPiProductSession(sessionId)) return;
    const shouldOpenStream = await prepareSessionStreamConnection(sessionId, options, {
      refreshSessionSlotMeta,
      rehydrateSessionSlotFromHistory,
    });
    if (!shouldOpenStream) {
      return;
    }

    closeSessionSlotStream(sessionId);
    if (options?.isCurrent && !options.isCurrent()) {
      return;
    }

    await openSessionStreamConnection({
      sessionId,
      cloudClient,
      options,
      createSessionStreamFlushController,
      refreshSessionSlotMeta,
      ensureSessionStreamConnected,
    });
  }, [
    closeSessionSlotStream,
    createSessionStreamFlushController,
    refreshSessionSlotMeta,
    rehydrateSessionSlotFromHistory,
    cloudClient,
  ]);

  return {
    closeSessionSlotStream,
    ensureSessionStreamConnected,
  };
}
