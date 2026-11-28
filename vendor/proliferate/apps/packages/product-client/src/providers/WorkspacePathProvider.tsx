import { isNativeProjectId, useWorkspaceQuery } from "@anyharness/sdk-react";
import { useProductHost } from "@proliferate/product-client/host/ProductHostProvider";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  normalizeRuntimeWorkspaceRoot,
  type RuntimeWorkspaceRootState,
  type WorkspaceFilesystemOriginState,
} from "#product/lib/domain/files/path-references";
import { resolveSelectedWorkspaceIdentity } from "#product/lib/domain/workspaces/selection/workspace-ui-key";
import { useProductWorkspaceConnectionResolver } from "#product/providers/ProductWorkspaceConnectionProvider";
import { useSessionSelectionStore } from "#product/stores/sessions/session-selection-store";

export interface WorkspacePathContextValue {
  materializedWorkspaceId: string | null;
  filesystemOrigin: WorkspaceFilesystemOriginState;
  workspaceRoot: RuntimeWorkspaceRootState;
}

const PENDING_FILESYSTEM_ORIGIN: WorkspaceFilesystemOriginState = {
  status: "pending",
  origin: null,
};
const PENDING_WORKSPACE_ROOT: RuntimeWorkspaceRootState = {
  status: "pending",
  path: null,
};

const WorkspacePathContext = createContext<WorkspacePathContextValue>({
  materializedWorkspaceId: null,
  filesystemOrigin: PENDING_FILESYSTEM_ORIGIN,
  workspaceRoot: PENDING_WORKSPACE_ROOT,
});

interface OriginResolution {
  materializedWorkspaceId: string | null;
  state: WorkspaceFilesystemOriginState;
}

export function WorkspacePathProvider({ children }: { children: ReactNode }) {
  const resolveConnection = useProductWorkspaceConnectionResolver();
  const scientificProject = useProductHost().desktop?.scientificProject;
  const selectedWorkspaceId = useSessionSelectionStore(
    (state) => state.selectedWorkspaceId,
  );
  const selectedLogicalWorkspaceId = useSessionSelectionStore(
    (state) => state.selectedLogicalWorkspaceId,
  );
  const { materializedWorkspaceId } = resolveSelectedWorkspaceIdentity({
    selectedLogicalWorkspaceId,
    materializedWorkspaceId: selectedWorkspaceId,
  });
  const native = isNativeProjectId(materializedWorkspaceId);
  const [nativeRoot, setNativeRoot] = useState<{ id: string; root: RuntimeWorkspaceRootState } | null>(null);
  const workspaceQuery = useWorkspaceQuery({
    workspaceId: materializedWorkspaceId,
    enabled: materializedWorkspaceId !== null && !native,
  });
  const [originResolution, setOriginResolution] = useState<OriginResolution>({
    materializedWorkspaceId: null,
    state: PENDING_FILESYSTEM_ORIGIN,
  });

  useEffect(() => {
    let current = true;
    setOriginResolution({
      materializedWorkspaceId,
      state: PENDING_FILESYSTEM_ORIGIN,
    });
    if (materializedWorkspaceId === null) {
      return () => {
        current = false;
      };
    }

    if (native) {
      const id = materializedWorkspaceId;
      setNativeRoot({id, root: PENDING_WORKSPACE_ROOT});
      const fail = () => {
        if (!current) return;
        setNativeRoot({id, root: {status: "unavailable", path: null}});
        setOriginResolution({materializedWorkspaceId: id, state: {status: "rejected", origin: null}});
      };
      if (!scientificProject) fail();
      else void scientificProject.identity().then(identity => {
        if (!current) return;
        const path = normalizeRuntimeWorkspaceRoot(identity.projectPath);
        if (identity.id !== id || path === null) { fail(); return; }
        setNativeRoot({id, root: {status: "settled", path}});
        setOriginResolution({materializedWorkspaceId: id, state: {status: "settled", origin: "desktop-local"}});
      }, fail);
      return () => { current = false; };
    }

    void resolveConnection(materializedWorkspaceId).then(
      (resolved) => {
        if (!current) return;
        setOriginResolution({
          materializedWorkspaceId,
          state: {
            status: "settled",
            origin: resolved.filesystemOrigin,
          },
        });
      },
      () => {
        if (!current) return;
        setOriginResolution({
          materializedWorkspaceId,
          state: { status: "rejected", origin: null },
        });
      },
    );

    return () => {
      current = false;
    };
  }, [materializedWorkspaceId, resolveConnection, native, scientificProject]);

  const filesystemOrigin = originResolution.materializedWorkspaceId === materializedWorkspaceId
    ? originResolution.state
    : PENDING_FILESYSTEM_ORIGIN;
  const workspaceRoot = useMemo<RuntimeWorkspaceRootState>(() => {
    if (native) return nativeRoot?.id === materializedWorkspaceId ? nativeRoot.root : PENDING_WORKSPACE_ROOT;
    if (materializedWorkspaceId === null || workspaceQuery.isPending) {
      return PENDING_WORKSPACE_ROOT;
    }
    if (workspaceQuery.isError) {
      return { status: "unavailable", path: null };
    }
    const path = normalizeRuntimeWorkspaceRoot(workspaceQuery.data?.path);
    return path === null
      ? { status: "unavailable", path: null }
      : { status: "settled", path };
  }, [materializedWorkspaceId, native, nativeRoot, workspaceQuery.data?.path, workspaceQuery.isError, workspaceQuery.isPending]);
  const value = useMemo<WorkspacePathContextValue>(() => ({
    materializedWorkspaceId,
    filesystemOrigin,
    workspaceRoot,
  }), [filesystemOrigin, materializedWorkspaceId, workspaceRoot]);

  return (
    <WorkspacePathContext.Provider value={value}>
      {children}
    </WorkspacePathContext.Provider>
  );
}

export function useWorkspacePath(): WorkspacePathContextValue {
  return useContext(WorkspacePathContext);
}
