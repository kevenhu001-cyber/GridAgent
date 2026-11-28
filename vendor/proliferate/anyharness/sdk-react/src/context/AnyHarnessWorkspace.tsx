import { createContext, type ReactNode, useContext } from "react";
import type {
  TerminalWebSocketAuthTransport, ListWorkspaceFilesResponse, SearchWorkspaceFilesResponse,
  ReadWorkspaceFileResponse, StatWorkspaceFileResponse, WriteWorkspaceFileRequest, WriteWorkspaceFileResponse,
} from "@anyharness/sdk";

/** Native scientific project file capability; no HTTP or external Agent dependency. */
export interface NativeProjectFiles {
  list(id: string, path: string): Promise<ListWorkspaceFilesResponse>;
  search(id: string, query: string, limit: number): Promise<SearchWorkspaceFilesResponse>;
  read(id: string, path: string): Promise<ReadWorkspaceFileResponse>;
  stat(id: string, path: string): Promise<StatWorkspaceFileResponse>;
  write(id: string, input: WriteWorkspaceFileRequest): Promise<WriteWorkspaceFileResponse>;
}

export function isNativeProjectId(id: string | null | undefined): id is string {
  return typeof id === "string" && id.startsWith("gridagent-scientific:");
}

/** A reserved identity may never fall through to the legacy filesystem. */
export function nativeProjectFiles(context: AnyHarnessWorkspaceContextValue, id: string | null | undefined) {
  if (!isNativeProjectId(id)) return null;
  if (!/^gridagent-scientific:[a-f0-9]{64}$/.test(id) || !context.nativeFiles) {
    throw new Error("Native scientific project file transport unavailable.");
  }
  return context.nativeFiles;
}

export interface AnyHarnessResolvedConnection {
  runtimeUrl: string;
  authToken?: string;
  anyharnessWorkspaceId: string;
  webSocketAuthTransport?: TerminalWebSocketAuthTransport;
}

export interface AnyHarnessWorkspaceContextValue {
  workspaceId: string | null;
  nativeFiles?: NativeProjectFiles;
  resolveConnection: (workspaceId: string) => Promise<AnyHarnessResolvedConnection>;
}

const AnyHarnessWorkspaceContext = createContext<AnyHarnessWorkspaceContextValue | null>(null);

export function AnyHarnessWorkspace({
  workspaceId,
  resolveConnection,
  nativeFiles,
  children,
}: AnyHarnessWorkspaceContextValue & { children: ReactNode }) {
  return (
    <AnyHarnessWorkspaceContext.Provider value={{ workspaceId, resolveConnection, nativeFiles }}>
      {children}
    </AnyHarnessWorkspaceContext.Provider>
  );
}

export function useAnyHarnessWorkspaceContext(): AnyHarnessWorkspaceContextValue {
  const context = useContext(AnyHarnessWorkspaceContext);
  if (!context) {
    throw new Error("AnyHarnessWorkspace provider is required.");
  }
  return context;
}

export async function resolveWorkspaceConnectionFromContext(
  context: AnyHarnessWorkspaceContextValue,
  workspaceIdOverride?: string | null,
): Promise<{ workspaceId: string; connection: AnyHarnessResolvedConnection }> {
  const workspaceId = workspaceIdOverride ?? context.workspaceId;
  if (!workspaceId) {
    throw new Error("No workspace selected.");
  }

  if (isNativeProjectId(workspaceId)) {
    throw new Error("Native scientific project has no AnyHarness connection.");
  }
  const connection = await context.resolveConnection(workspaceId);
  const runtimeUrl = connection.runtimeUrl.trim();
  const anyharnessWorkspaceId = connection.anyharnessWorkspaceId.trim();
  if (!runtimeUrl) {
    throw new Error("AnyHarness runtime URL is required.");
  }
  if (!anyharnessWorkspaceId) {
    throw new Error("AnyHarness workspace ID is required.");
  }

  return {
    workspaceId,
    connection: {
      runtimeUrl,
      authToken: connection.authToken,
      anyharnessWorkspaceId,
      webSocketAuthTransport: connection.webSocketAuthTransport,
    },
  };
}
