// @vitest-environment jsdom

import type { Workspace } from "@anyharness/sdk";
import type { DesktopPiBridge, PiEvent } from "@proliferate/product-client/host/desktop-bridge";
import { closePiProductSession, ownsPiSession } from "#product/lib/access/pi/product-session";
import type { ReactNode } from "react";
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderableOutboxEntriesForTranscript } from "#product/domain/sessions/intents/session-intent-selectors";
import {
  buildPendingWorkspaceUiKey,
  buildSubmittingPendingWorkspaceEntry,
} from "#product/lib/domain/workspaces/creation/pending-entry";
import {
  createEmptySessionRecord,
  getSessionRecord,
  putSessionRecord,
} from "#product/stores/sessions/session-records";
import {
  getPromptOutboxEntriesForSession,
  useSessionIntentStore,
} from "#product/stores/sessions/session-intent-store";
import { useSessionDirectoryStore } from "#product/stores/sessions/session-directory-store";
import { useSessionSelectionStore } from "#product/stores/sessions/session-selection-store";
import {
  EMPTY_PENDING_WORKSPACE_REGISTRY,
  upsertPendingWorkspaceEntry,
} from "#product/lib/domain/workspaces/creation/pending-entry-registry";
import {
  MAX_CONCURRENT_PENDING_LAUNCHES,
} from "#product/lib/domain/workspaces/creation/launch-concurrency";
import { useSessionTranscriptStore } from "#product/stores/sessions/session-transcript-store";
import {
  launchIntents,
} from "#product/lib/domain/chat/launch/launch-intent-registry";
import { useChatLaunchIntentStore } from "#product/stores/chat/chat-launch-intent-store";
import { useDeferredHomeLaunchStore } from "#product/stores/home/deferred-home-launch-store";
import { useHomeNextLaunch } from "#product/hooks/home/workflows/use-home-next-launch";
import type {
  HomeLaunchTarget,
  HomeNextLaunchOutcome,
} from "#product/lib/domain/home/home-next-launch";
import { CoworkThreadLaunchProvider } from "#product/providers/CoworkThreadLaunchProvider";

import {
  renderHomeNextLaunch,
  sessionIdForAttempt,
} from "#product/hooks/home/workflows/use-home-next-launch.test-support";

const mocks = vi.hoisted(() => {
  const createThreadFromSelection = vi.fn();
  return {
    createEmptySessionWithResolvedConfig: vi.fn(),
    createLocalWorkspaceAndEnterWithResult: vi.fn(),
    createSessionWithResolvedConfig: vi.fn(),
    createThreadFromSelection,
    createWorktreeAndEnterWithResult: vi.fn(),
    navigate: vi.fn(),
    productHost: { desktop: {} as object | null },
    pi: undefined as DesktopPiBridge | undefined,
    localWorkspaces: [] as Workspace[],
    selectWorkspace: vi.fn(),
    showToast: vi.fn(),
    showErrorToast: vi.fn(),
    useCoworkThreadWorkflow: vi.fn(() => ({ createThreadFromSelection })),
  };
});

vi.mock("#product/hooks/chat/derived/use-pi-model-selector", () => ({
  usePiMode: () => ({mode:mocks.pi?"native":"legacy",pi:mocks.pi}),
  usePiModelSelector: () => ({mode:mocks.pi?"native":"legacy",
    selection:mocks.pi?{kind:"openai",modelId:"model"}:null,props:{
      connectionState:"healthy",currentModel:null,groups:[],hasAgents:false,isLoading:false,onSelect:()=>{},
    }}),
}));

vi.mock("react-router-dom", async (importOriginal) => ({
  ...await importOriginal<typeof import("react-router-dom")>(),
  useLocation: () => ({ pathname: "/" }),
  useNavigate: () => mocks.navigate,
}));

vi.mock("@proliferate/product-client/host/ProductHostProvider", () => ({
  useProductHost: () => mocks.productHost,
}));

vi.mock("#product/stores/toast/toast-store", () => ({
  useToastStore: (selector: (state: Record<string, unknown>) => unknown) =>
    selector({ show: mocks.showToast, showError: mocks.showErrorToast }),
}));

vi.mock("#product/hooks/cowork/workflows/use-cowork-thread-workflow", () => ({
  useCoworkThreadWorkflow: mocks.useCoworkThreadWorkflow,
}));

vi.mock("#product/hooks/workspaces/workflows/use-workspace-entry-actions", () => ({
  useWorkspaceEntryActions: () => ({
    createLocalWorkspaceAndEnterWithResult: mocks.createLocalWorkspaceAndEnterWithResult,
    createWorktreeAndEnterWithResult: mocks.createWorktreeAndEnterWithResult,
  }),
}));

vi.mock("#product/hooks/workspaces/workflows/selection/use-workspace-selection", () => ({
  useWorkspaceSelection: () => ({
    selectWorkspace: mocks.selectWorkspace,
  }),
}));

vi.mock("#product/hooks/workspaces/cache/use-workspaces", () => ({
  useWorkspaces: () => ({ data: { workspaces: mocks.localWorkspaces,localWorkspaces:mocks.localWorkspaces } }),
}));

vi.mock("#product/hooks/sessions/workflows/use-session-creation-actions", () => ({
  useSessionCreationActions: () => ({
    createEmptySessionWithResolvedConfig: mocks.createEmptySessionWithResolvedConfig,
    createSessionWithResolvedConfig: mocks.createSessionWithResolvedConfig,
  }),
}));

vi.mock("#product/hooks/workspaces/derived/use-workspace-runtime-block", () => ({
  useWorkspaceRuntimeBlock: () => ({
    getWorkspaceRuntimeBlockReason: () => null,
  }),
}));

vi.mock("#product/hooks/sessions/workflows/use-session-interaction-resolution-actions", () => ({
  useSessionInteractionResolutionActions: () => ({
    resolvePermission: vi.fn(),
    resolveMcpElicitation: vi.fn(),
    resolveUserInput: vi.fn(),
    revealMcpElicitationUrl: vi.fn(),
  }),
}));

// Routing half: which workflow a Home launch target reaches, and how the
// launch intent is scoped to its own pending attempt. The concurrency cases
// (two live launches, the cap, failure announcement, prompt dedupe) live in
// `use-home-next-launch.concurrency.test.tsx`; the file-size gate splits them.

describe("useHomeNextLaunch", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.productHost.desktop = {};
    mocks.pi=undefined;
    mocks.localWorkspaces=[];
    useSessionDirectoryStore.getState().clearEntries();
    useSessionTranscriptStore.getState().clearEntries();
    useSessionIntentStore.getState().clear();
    useSessionSelectionStore.getState().clearSelection();
    useChatLaunchIntentStore.setState({ intentsById: {}, intentOrder: [] });
    useDeferredHomeLaunchStore.setState({ launches: {} });
  });

  afterEach(cleanup);

  it("launches native Home into the retained workspace and prompt outbox without external Agent creation",async()=>{
    const id="e".repeat(32);
    const events:PiEvent[]=[{kind:"ready",version:1}];
    const bridge:DesktopPiBridge={
      mode:vi.fn(async()=>true),matchesWorkspace:vi.fn(async()=>true),open:vi.fn(async()=>id),
      prompt:vi.fn(async()=>"f".repeat(32)),abort:vi.fn(async()=>{}),poll:vi.fn(async()=>events.splice(0)),
      close:vi.fn(async()=>{}),
    };
    mocks.pi=bridge;
    mocks.localWorkspaces=[{id:"native-workspace",kind:"worktree",repoRootId:"repo",path:"/project",
      surface:"standard",originalBranch:"main",currentBranch:"main",availability:"available",
      lifecycleState:"active",createdAt:"2026-11-28T00:00:00Z",updatedAt:"2026-11-28T00:00:00Z"}];
    mocks.selectWorkspace.mockImplementation(async()=>useSessionSelectionStore.getState().activateWorkspace({
      logicalWorkspaceId:"native-workspace",workspaceId:"native-workspace",initialActiveSessionId:null,
    }));
    const {result}=renderHomeNextLaunch();
    try {
      let outcome:HomeNextLaunchOutcome="refused";
      await act(async()=>{outcome=await result.current.launch({text:"calculate",modelSelection:{kind:"openai",modelId:"model"},
        target:{kind:"local",sourceRoot:"/project",existingWorkspaceId:"native-workspace"}});});
      expect(outcome).toBe("launched");
      expect(getSessionRecord(id)?.agentKind).toBe("pi");
      expect(useSessionSelectionStore.getState().activeSessionId).toBe(id);
      expect(getPromptOutboxEntriesForSession(id)).toHaveLength(1);
      expect(mocks.navigate).toHaveBeenCalledWith("/");
      expect(bridge.prompt).not.toHaveBeenCalled();
      expect(mocks.createSessionWithResolvedConfig).not.toHaveBeenCalled();
      expect(mocks.createLocalWorkspaceAndEnterWithResult).not.toHaveBeenCalled();
      expect(mocks.createThreadFromSelection).not.toHaveBeenCalled();
    } finally {
      useSessionIntentStore.getState().clear();
      if(ownsPiSession(id)) await closePiProductSession(id);
    }
  });

  it("projects one destination prompt for a Home worktree launch", async () => {
    const sessionId = "client-session:codex:home-worktree";
    const pendingEntry = buildSubmittingPendingWorkspaceEntry({
      attemptId: "home-worktree-attempt",
      selectedWorkspaceId: null,
      source: "worktree-created",
      displayName: "home-worktree",
      repoLabel: "repo",
      baseBranchName: "main",
      request: {
        kind: "worktree",
        input: {
          repoRootId: "repo-root-1",
          sourceWorkspaceId: null,
          baseBranch: "main",
          defaultBranch: "main",
        },
      },
    });
    const pendingWorkspaceId = buildPendingWorkspaceUiKey(pendingEntry);

    mocks.createWorktreeAndEnterWithResult.mockImplementation(async () => {
      putSessionRecord(createEmptySessionRecord(sessionId, "codex", {
        workspaceId: pendingWorkspaceId,
        materializedSessionId: null,
        modelId: "gpt-5.4",
      }));
      useSessionSelectionStore.getState().enterPendingWorkspaceShell(pendingEntry, {
        initialActiveSessionId: sessionId,
      });
      return {
        workspaceId: "workspace-real",
        projectedSessionId: sessionId,
      };
    });

    const { result } = renderHomeNextLaunch();
    let outcome: HomeNextLaunchOutcome = "refused";
    await act(async () => {
      outcome = await result.current.launch({
        text: "build the projected destination",
        modelSelection: { kind: "codex", modelId: "gpt-5.4" },
        launchControlValues: {},
        target: {
          kind: "worktree",
          repoRootId: "repo-root-1",
          sourceWorkspaceId: null,
          baseBranch: "main",
          defaultBranch: "main",
        },
      });
    });

    const record = getSessionRecord(sessionId);
    const promptIntents = getPromptOutboxEntriesForSession(sessionId);
    const destinationPromptRows = record
      ? renderableOutboxEntriesForTranscript(promptIntents, record.transcript)
      : [];

    expect(outcome).toBe("launched");
    expect(promptIntents).toHaveLength(1);
    expect(destinationPromptRows).toHaveLength(1);
    expect(destinationPromptRows[0]?.text).toBe("build the projected destination");
    expect(mocks.createSessionWithResolvedConfig).not.toHaveBeenCalled();
    expect(mocks.navigate).toHaveBeenCalledTimes(1);
  });

  // PR #1867 review finding 1: the intent used to stay unscoped
  // (attemptId/targetWorkspaceId/materializedWorkspaceId all null) for the
  // entire in-flight window on the success path, because
  // markHomeLaunchIntentMaterializedFromPendingWorkspace was only called from
  // the catch block. This pins that the launch flow now scopes the intent to
  // its pending attempt synchronously, right after invoking the create call
  // and before awaiting it — not only after the create promise settles.
  it("scopes the launch intent to its pending attempt before the create promise resolves (PRO-230)", async () => {
    const sessionId = "client-session:codex:sync-scope";

    let resolveCreate: (value: { workspaceId: string; projectedSessionId: string | null }) => void =
      () => {};
    const createPromise = new Promise<{ workspaceId: string; projectedSessionId: string | null }>(
      (resolve) => {
        resolveCreate = resolve;
      },
    );
    let mintedAttemptId: string | null = null;
    let pendingEntry: ReturnType<typeof buildSubmittingPendingWorkspaceEntry> | null = null;
    // Mirrors production: use-home-next-launch.ts pre-mints the attempt id
    // and threads it through as an option; the create workflow's own
    // beginPendingWorkspace call (registered here under that same id) runs
    // synchronously, before its first await, so the pending entry is already
    // in the registry by the time the caller gets the promise back.
    mocks.createWorktreeAndEnterWithResult.mockImplementation((_input, options) => {
      mintedAttemptId = options.attemptId;
      pendingEntry = buildSubmittingPendingWorkspaceEntry({
        attemptId: options.attemptId,
        selectedWorkspaceId: null,
        source: "worktree-created",
        displayName: "sync-scope",
        repoLabel: "repo",
        baseBranchName: "main",
        request: {
          kind: "worktree",
          input: {
            repoRootId: "repo-root-1",
            sourceWorkspaceId: null,
            baseBranch: "main",
            defaultBranch: "main",
          },
        },
      });
      useSessionSelectionStore.getState().enterPendingWorkspaceShell(pendingEntry, {
        initialActiveSessionId: sessionId,
      });
      return createPromise;
    });

    const { result } = renderHomeNextLaunch();

    let launchPromise: Promise<HomeNextLaunchOutcome> = Promise.resolve("refused");
    act(() => {
      launchPromise = result.current.launch({
        text: "scope before resolve",
        modelSelection: { kind: "codex", modelId: "gpt-5.4" },
        launchControlValues: {},
        target: {
          kind: "worktree",
          repoRootId: "repo-root-1",
          sourceWorkspaceId: null,
          baseBranch: "main",
          defaultBranch: "main",
        },
      });
    });

    // The create promise is still pending here, so if scoping only happened
    // in the catch block (the pre-fix behavior), attemptId would still be
    // null at this point.
    expect(mintedAttemptId).not.toBeNull();
    expect(launchIntents(useChatLaunchIntentStore.getState())[0]?.attemptId)
      .toBe(mintedAttemptId);

    putSessionRecord(createEmptySessionRecord(sessionId, "codex", {
      workspaceId: buildPendingWorkspaceUiKey(pendingEntry!),
      materializedSessionId: null,
      modelId: "gpt-5.4",
    }));
    resolveCreate({ workspaceId: "workspace-real", projectedSessionId: sessionId });

    let outcome: HomeNextLaunchOutcome = "refused";
    await act(async () => {
      outcome = await launchPromise;
    });
    expect(outcome).toBe("launched");
  });

  it("does not invoke the Desktop Cowork workflow from Web Home", async () => {
    mocks.productHost.desktop = null;
    const { result } = renderHomeNextLaunch();

    let outcome: HomeNextLaunchOutcome = "launched";
    await act(async () => {
      outcome = await result.current.launch({
        text: "start cowork on web",
        modelSelection: { kind: "codex", modelId: "gpt-5.4" },
        launchControlValues: {},
        target: { kind: "cowork" },
      });
    });

    expect(outcome).toBe("refused");
    expect(result.current.isLaunching).toBe(false);
    expect(mocks.useCoworkThreadWorkflow).not.toHaveBeenCalled();
    expect(mocks.createThreadFromSelection).not.toHaveBeenCalled();
    expect(mocks.navigate).not.toHaveBeenCalled();
    expect(useChatLaunchIntentStore.getState().intentOrder).toEqual([]);
    expect(mocks.showToast).toHaveBeenCalledWith(
      "Cowork threads are available in the Desktop app.",
      "info",
    );
  });

  it("still invokes the Cowork workflow from Desktop Home", async () => {
    mocks.createThreadFromSelection.mockResolvedValue(null);
    const { result } = renderHomeNextLaunch();

    await act(async () => {
      await result.current.launch({
        text: "start cowork on desktop",
        modelSelection: { kind: "codex", modelId: "gpt-5.4" },
        launchControlValues: {},
        target: { kind: "cowork" },
      });
    });

    expect(mocks.useCoworkThreadWorkflow).toHaveBeenCalledTimes(1);
    expect(mocks.createThreadFromSelection).toHaveBeenCalledTimes(1);
  });

  it("stops a dismissed Cowork launch quietly, like local and worktree (PRO-230)", async () => {
    // A null result is a dismissal, not a failure: the same shape that the
    // local and worktree branches already treat as a quiet stop.
    mocks.createThreadFromSelection.mockResolvedValue(null);
    const { result } = renderHomeNextLaunch();

    let outcome: HomeNextLaunchOutcome = "launched";
    await act(async () => {
      outcome = await result.current.launch({
        text: "start cowork on desktop",
        modelSelection: { kind: "codex", modelId: "gpt-5.4" },
        launchControlValues: {},
        target: { kind: "cowork" },
      });
    });

    expect(outcome).toBe("not-started");
    expect(mocks.showErrorToast).not.toHaveBeenCalled();
    expect(useChatLaunchIntentStore.getState().intentOrder).toEqual([]);
    // The attempt id is minted by the caller, so intent and prompt routing can
    // scope to this attempt instead of whichever entry happens to be attended.
    expect(mocks.createThreadFromSelection.mock.calls[0]?.[0]?.attemptId)
      .toEqual(expect.any(String));
  });

  it.each([
    {
      label: "local",
      target: { kind: "local", sourceRoot: "/repo", existingWorkspaceId: null },
    },
    {
      label: "worktree",
      target: {
        kind: "worktree",
        repoRootId: "repo-root-1",
        sourceWorkspaceId: null,
        baseBranch: "main",
        defaultBranch: "main",
      },
    },
  ])("rejects a forged $label launch before Web local workflows", async ({ target }) => {
    mocks.productHost.desktop = null;
    const { result } = renderHomeNextLaunch();

    let outcome: HomeNextLaunchOutcome = "launched";
    await act(async () => {
      outcome = await result.current.launch({
        text: "do not launch locally",
        modelSelection: { kind: "codex", modelId: "gpt-5.4" },
        launchControlValues: {},
        target: target as HomeLaunchTarget,
      });
    });

    expect(outcome).toBe("refused");
    expect(mocks.useCoworkThreadWorkflow).not.toHaveBeenCalled();
    expect(mocks.createLocalWorkspaceAndEnterWithResult).not.toHaveBeenCalled();
    expect(mocks.createWorktreeAndEnterWithResult).not.toHaveBeenCalled();
    expect(useChatLaunchIntentStore.getState().intentOrder).toEqual([]);
    expect(mocks.showToast).toHaveBeenCalledWith(
      "Local launch targets are available in the Desktop app.",
      "info",
    );
  });

  it("refuses a stale cloud target with a not-started outcome (the cloud stack is deleted)", async () => {
    mocks.productHost.desktop = null;
    const { result } = renderHomeNextLaunch();
    let outcome: HomeNextLaunchOutcome = "launched";

    await act(async () => {
      outcome = await result.current.launch({
        text: "launch in cloud",
        modelSelection: { kind: "codex", modelId: "gpt-5.4" },
        launchControlValues: {},
        target: {
          kind: "cloud",
          gitOwner: "proliferate-ai",
          gitRepoName: "proliferate",
          baseBranch: "main",
        },
      });
    });

    expect(outcome).toBe("not-started");
    expect(mocks.useCoworkThreadWorkflow).not.toHaveBeenCalled();
    expect(mocks.createLocalWorkspaceAndEnterWithResult).not.toHaveBeenCalled();
    expect(mocks.createWorktreeAndEnterWithResult).not.toHaveBeenCalled();
  });
});
