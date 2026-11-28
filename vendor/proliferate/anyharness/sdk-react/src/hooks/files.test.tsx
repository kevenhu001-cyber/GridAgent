// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnyHarnessRuntime } from "../context/AnyHarnessRuntime.js";
import { AnyHarnessWorkspace, type NativeProjectFiles } from "../context/AnyHarnessWorkspace.js";
import { useStatWorkspaceFileQuery, useWorkspaceFilesQuery, useWriteWorkspaceFileMutation, useDeleteWorkspaceEntryMutation } from "./files.js";

const mocks = vi.hoisted(() => ({
  stat: vi.fn(),
}));

vi.mock("../lib/client-cache.js", () => ({
  getAnyHarnessClient: () => ({
    files: {
      stat: mocks.stat,
    },
  }),
}));

describe("workspace file stat query", () => {
  afterEach(() => {
    cleanup();
    mocks.stat.mockReset();
  });

  it("stats the workspace root when the path is empty", async () => {
    mocks.stat.mockResolvedValue({
      path: "",
      kind: "directory",
    });
    const queryClient = createQueryClient();

    const { result } = renderHook(
      () => useStatWorkspaceFileQuery({ path: "" }),
      { wrapper: createWrapper(queryClient) },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(mocks.stat).toHaveBeenCalledOnce();
    expect(mocks.stat).toHaveBeenCalledWith(
      "anyharness-workspace-1",
      "",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("does not stat when the path is null", async () => {
    const queryClient = createQueryClient();

    const { result } = renderHook(
      () => useStatWorkspaceFileQuery({ path: null }),
      { wrapper: createWrapper(queryClient) },
    );

    await waitFor(() => expect(result.current.fetchStatus).toBe("idle"));
    expect(mocks.stat).not.toHaveBeenCalled();
  });
});

function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
}

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <AnyHarnessRuntime runtimeUrl="http://runtime-files.test">
          <AnyHarnessWorkspace
            workspaceId="workspace-1"
            resolveConnection={async () => ({
              runtimeUrl: "http://runtime-files.test",
              anyharnessWorkspaceId: "anyharness-workspace-1",
            })}
          >
            {children}
          </AnyHarnessWorkspace>
        </AnyHarnessRuntime>
      </QueryClientProvider>
    );
  };
}


describe("native scientific project file routing", () => {
  const id = "gridagent-scientific:" + "a".repeat(64);
  const makeNative = (): NativeProjectFiles => ({
    list: vi.fn(async (_id: string, path: string) => ({directoryPath: path, entries: []})),
    search: vi.fn(async () => ({results: []})),
    read: vi.fn(async () => ({path: "study.py", kind: "file" as const, content: "x=1",
      versionToken: "a".repeat(64), encoding: "utf-8", sizeBytes: 3, isText: true, tooLarge: false})),
    stat: vi.fn(async (_id: string, path: string) => ({path, kind: "directory" as const})),
    write: vi.fn(async (_id: string, input) => ({path: input.path, versionToken: "b".repeat(64), sizeBytes: 3})),
  });

  function wrapper(nativeFiles?: NativeProjectFiles) {
    const queryClient = createQueryClient();
    const legacy = vi.fn(async () => { throw new Error("Legacy runtime must not be called"); });
    return {legacy, wrap: function Wrapper({children}: {children: ReactNode}) {
      return <QueryClientProvider client={queryClient}>
        <AnyHarnessRuntime runtimeUrl={null}>
          <AnyHarnessWorkspace workspaceId={id} resolveConnection={legacy} nativeFiles={nativeFiles}>
            {children}
          </AnyHarnessWorkspace>
        </AnyHarnessRuntime>
      </QueryClientProvider>;
    }};
  }

  afterEach(cleanup);

  it("lists and saves under the same native identity without a runtime", async () => {
    const native = makeNative();
    const {wrap, legacy} = wrapper(native);
    const {result} = renderHook(() => ({
      tree: useWorkspaceFilesQuery({path: "models"}),
      save: useWriteWorkspaceFileMutation(),
    }), {wrapper: wrap});
    await waitFor(() => expect(result.current.tree.isSuccess).toBe(true));
    expect(native.list).toHaveBeenCalledWith(id, "models");
    const input = {path: "models/study.py", content: "x=2", expectedVersionToken: "a".repeat(64)};
    await result.current.save.mutateAsync(input);
    expect(native.write).toHaveBeenCalledWith(id, input);
    expect(legacy).not.toHaveBeenCalled();
  });

  it("fails closed when native capability is absent or an operation is unsupported", async () => {
    const {wrap, legacy} = wrapper();
    const {result} = renderHook(() => ({
      tree: useWorkspaceFilesQuery({}),
      remove: useDeleteWorkspaceEntryMutation(),
    }), {wrapper: wrap});
    await waitFor(() => expect(result.current.tree.isError).toBe(true));
    await expect(result.current.remove.mutateAsync({path: "study.py"})).rejects.toThrow("no AnyHarness connection");
    expect(legacy).not.toHaveBeenCalled();
  });
});
