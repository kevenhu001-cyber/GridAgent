import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { PI_CREDENTIAL_STATUS_QUERY_KEY } from "#product/hooks/chat/derived/use-pi-model-selector";
import type { DesktopPiCredentialBridge, PiCredentialStatus, PiProvider } from "@proliferate/product-client/host/desktop-bridge";
import { ProliferateClientError } from "@proliferate/cloud-sdk";
import {
  useAgentApiKeys,
  useCreateAgentApiKey,
  useRevokeAgentApiKey,
} from "@proliferate/cloud-sdk-react";
import { Plus } from "#product/primitives/icons/core";
import { Button } from "#product/primitives/Button";
import { ConfirmationDialog } from "#product/primitives/patterns/ConfirmationDialog";
import { PageHeader } from "#product/primitives/patterns/PageHeader";
import { SettingsEmptyState } from "#product/primitives/patterns/settings/SettingsEmptyState";
import { SettingsPageBody } from "#product/primitives/patterns/settings/SettingsPageBody";
import { SettingsRow } from "#product/primitives/patterns/settings/SettingsRow";
import { SettingsSection } from "#product/primitives/patterns/settings/SettingsSection";
import { ApiKeyCreatorModal, type ApiKeyCreatorSubmit } from "#product/components/settings/panes/agent-auth/ApiKeyCreatorModal";
import { AGENT_API_KEYS_COPY } from "#product/copy/settings/agent-api-keys-copy";
import { useCloudAvailabilityState } from "#product/hooks/cloud/derived/use-cloud-availability-state";
import { useToastStore } from "#product/stores/toast/toast-store";

// A 409 from the revoke endpoint carries the harnesses whose enabled selections
// still wire the key (contract §5); surface them so the user knows what to
// disable first.
function revokeConflictHarnesses(error: unknown): string[] | null {
  if (error instanceof ProliferateClientError && error.status === 409) {
    const harnesses = error.details.harnesses;
    if (Array.isArray(harnesses) && harnesses.every((h) => typeof h === "string")) {
      return harnesses as string[];
    }
  }
  return null;
}

function formatCreatedAt(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
}

type KeyRow = { id: string; title: string; redactedHint: string; createdAt?: string };
type KeysQuery = { data?: readonly KeyRow[]; isLoading: boolean; isError: boolean; refetch(): Promise<unknown> };
type PaneSource = {
  keysQuery: KeysQuery; authReady: boolean; unreachable: boolean; local: boolean;
  createPending: boolean; revokePending: boolean;
  create(input: ApiKeyCreatorSubmit, done: () => void): void;
  revoke(id: string, done: () => void): void;
};

export function ApiKeysPane({local}: {local?: DesktopPiCredentialBridge} = {}) {
  return local ? <NativeApiKeysPane bridge={local} /> : <CloudApiKeysPane />;
}

function CloudApiKeysPane() {
  const { authStatus, controlPlaneReachable } = useCloudAvailabilityState();
  const showToast = useToastStore(state => state.show);
  const authReady = authStatus === "authenticated" && controlPlaneReachable;
  const keysQuery = useAgentApiKeys(authReady);
  const createKey = useCreateAgentApiKey();
  const revokeKey = useRevokeAgentApiKey();
  return <ApiKeysView source={{
    keysQuery, authReady, unreachable: authStatus === "authenticated" && !controlPlaneReachable, local: false,
    createPending: createKey.isPending, revokePending: revokeKey.isPending,
    create: (input, done) => createKey.mutate({title: input.title, value: input.value}, {
      onSuccess: created => { done(); showToast(`Added API key ${created.title}.`, "info"); },
      onError: error => showToast(error.message || AGENT_API_KEYS_COPY.addError),
    }),
    revoke: (id, done) => revokeKey.mutate(id, {
      onSuccess: () => {done(); showToast(AGENT_API_KEYS_COPY.revokedToast, "info");},
      onError: error => {
        done();
        const harnesses = revokeConflictHarnesses(error);
        showToast(harnesses ? AGENT_API_KEYS_COPY.revokeReferencedError(harnesses) : error.message || AGENT_API_KEYS_COPY.revokeError);
      },
    }),
  }} />;
}

const providers: Record<PiProvider, string> = {openai:"OpenAI", anthropic:"Anthropic", google:"Google"};
function providerForEnv(name: string): PiProvider | undefined {
  switch(name) {
    case "OPENAI_API_KEY": return "openai";
    case "ANTHROPIC_API_KEY": return "anthropic";
    case "GOOGLE_API_KEY": return "google";
    default: return undefined;
  }
}

function NativeApiKeysPane({bridge}: {bridge: DesktopPiCredentialBridge}) {
  const queryClient = useQueryClient();
  const showToast = useToastStore(state => state.show);
  const [records, setRecords] = useState<PiCredentialStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [pending, setPending] = useState<"save" | "remove" | null>(null);
  const generation = useRef(0);
  const busy = useRef(false);
  async function refresh() {
    const current = ++generation.current;
    setLoading(true);
    setError(false);
    try {
      const rows = await bridge.list();
      if (generation.current === current) setRecords(rows);
    } catch {
      if (generation.current === current) setError(true);
    } finally {
      if (generation.current === current) setLoading(false);
    }
  }
  useEffect(() => {
    void refresh();
    return () => {generation.current++;};
  // The bridge identity owns the native credential scope.
  }, [bridge]);

  // Secrets go directly to the native host; never React Query's mutation cache,
  // localStorage, cloud SDK, transcript or diagnostic output.
  async function write(kind: "save" | "remove", operation: () => Promise<void>, done: () => void) {
    if (busy.current) return;
    busy.current = true;
    setPending(kind);
    try {
      await operation();
      void queryClient.invalidateQueries({queryKey:PI_CREDENTIAL_STATUS_QUERY_KEY});
      done();
      showToast(kind === "save" ? "API key saved locally." : "Local API key removed.", "info");
      await refresh();
    } catch {
      showToast(kind === "save" ? "Could not save the local API key." : "Could not remove the local API key.");
    } finally {
      busy.current = false;
      setPending(null);
    }
  }
  return <ApiKeysView source={{
    keysQuery: {data: records.filter(row=>row.configured).map(row=>({
      id:row.provider, title:providers[row.provider], redactedHint:"••••••••",
    })), isLoading:loading, isError:error, refetch:refresh},
    authReady:true, unreachable:false, local:true, createPending:pending==="save", revokePending:pending==="remove",
    create: (input, done) => {
      const provider = providerForEnv(input.envVarName);
      if (!provider) {showToast("Use OPENAI_API_KEY, ANTHROPIC_API_KEY or GOOGLE_API_KEY."); return;}
      void write("save", () => bridge.save(provider,input.value), done);
    },
    revoke: (id,done) => {
      if (!Object.hasOwn(providers,id)) return;
      void write("remove", () => bridge.remove(id as PiProvider), done);
    },
  }} />;
}

function ApiKeysView({source}: {source: PaneSource}) {
  const {keysQuery, authReady, unreachable, local} = source;
  const description = local ? "Provider credentials stored in the system credential manager." : AGENT_API_KEYS_COPY.description;
  const [addOpen, setAddOpen] = useState(false);
  const [pendingRevoke, setPendingRevoke] = useState<KeyRow | null>(null);
  const [isRetrying, setIsRetrying] = useState(false);
  const retryInFlight = useRef(false);
  const retryGeneration = useRef(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      retryGeneration.current += 1;
      retryInFlight.current = false;
    };
  }, []);

  const keys = keysQuery.data ?? [];
  function handleCreate(input: ApiKeyCreatorSubmit) {
    source.create(input, () => setAddOpen(false));
  }
  function handleConfirmRevoke() {
    if (pendingRevoke) source.revoke(pendingRevoke.id, () => setPendingRevoke(null));
  }

  function handleRetry() {
    if (retryInFlight.current) {
      return;
    }
    retryInFlight.current = true;
    const generation = retryGeneration.current + 1;
    retryGeneration.current = generation;
    setIsRetrying(true);
    void (async () => {
      try {
        await keysQuery.refetch();
      } catch {
        // The query error state is the recovery surface; consume transport
        // rejections so Retry can return to a usable state.
      } finally {
        if (!mounted.current || retryGeneration.current !== generation) {
          return;
        }
        retryInFlight.current = false;
        setIsRetrying(false);
      }
    })();
  }

  if (!authReady) {
    // Truthful cause: a signed-in user whose control plane is unreachable gets
    // a connectivity explanation, not a "sign in" prompt they can't act on
    // (PR2-GATING-01 class). Anonymous users still get the sign-in prompt.

    return (
      <SettingsPageBody data-api-keys-pane="" data-api-keys-state="gated">
        <PageHeader
          variant="flat"
          title={AGENT_API_KEYS_COPY.title}
          description={description}
        />
        <SettingsEmptyState
          size="compact"
          title={unreachable
            ? AGENT_API_KEYS_COPY.serverUnreachableTitle
            : AGENT_API_KEYS_COPY.signInRequiredTitle}
          description={unreachable
            ? AGENT_API_KEYS_COPY.serverUnreachable
            : AGENT_API_KEYS_COPY.signInRequired}
        />
      </SettingsPageBody>
    );
  }

  const keysState = keysQuery.isLoading
    ? "loading"
    : keysQuery.isError
      ? "error"
      : "ready";

  return (
    <SettingsPageBody data-api-keys-pane="" data-api-keys-state={keysState}>
      <PageHeader
        variant="flat"
        title={AGENT_API_KEYS_COPY.title}
        description={description}
        action={
          <Button
            type="button"
            variant="secondary"
            size="sm"
            className="gap-1.5"
            onClick={() => setAddOpen(true)}
          >
            <Plus className="icon-paired" />
            {AGENT_API_KEYS_COPY.addAction}
          </Button>
        }
      />

      {keysQuery.isLoading ? (
        <div className="text-ui-sm text-muted-foreground">{AGENT_API_KEYS_COPY.loading}</div>
      ) : keysQuery.isError ? (
        <SettingsEmptyState
          size="compact"
          title={local ? "Could not load native credentials." : AGENT_API_KEYS_COPY.loadError}
          action={
            <Button
              type="button"
              variant="secondary"
              size="sm"
              loading={isRetrying}
              onClick={handleRetry}
            >
              {isRetrying
                ? AGENT_API_KEYS_COPY.retryingAction
                : AGENT_API_KEYS_COPY.retryAction}
            </Button>
          }
        />
      ) : keys.length === 0 ? (
        <SettingsEmptyState
          size="compact"
          title={AGENT_API_KEYS_COPY.emptyTitle}
          description={local ? "Add a provider key for Pi." : AGENT_API_KEYS_COPY.emptyDescription}
        />
      ) : (
        <SettingsSection title={AGENT_API_KEYS_COPY.keysSection}>
          {keys.map((key) => (
            <SettingsRow
              key={key.id}
              label={
                <span className="flex min-w-0 items-center gap-2">
                  <span className="truncate">{key.title}</span>
                  <span className="font-mono text-ui-sm font-normal text-muted-foreground">
                    {key.redactedHint}
                  </span>
                </span>
              }
              description={local ? "Saved locally" : AGENT_API_KEYS_COPY.createdDetail(formatCreatedAt(key.createdAt ?? ""))}
            >
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setPendingRevoke(key)}
              >
                {local ? "Remove" : AGENT_API_KEYS_COPY.revokeAction}
              </Button>
            </SettingsRow>
          ))}
        </SettingsSection>
      )}

      <ApiKeyCreatorModal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        heading={AGENT_API_KEYS_COPY.addModalHeading}
        description={local ? "Save or replace the key for the selected provider. Existing sessions keep their current credentials until restarted." : AGENT_API_KEYS_COPY.addModalDescription}
        showTitleField={!local}
        envVarField={local ? {label:"Provider credential",placeholder:"OPENAI_API_KEY",helpText:"OPENAI_API_KEY, ANTHROPIC_API_KEY or GOOGLE_API_KEY"} : undefined}
        submitLabel={AGENT_API_KEYS_COPY.addAction}
        submitting={source.createPending}
        error={null}
        onSubmit={handleCreate}
      />

      <ConfirmationDialog
        open={pendingRevoke !== null}
        title={local ? "Remove local API key" : AGENT_API_KEYS_COPY.revokeTitle}
        description={pendingRevoke
          ? (local ? `Remove ${pendingRevoke.title} from this device? This does not revoke the provider key remotely or stop an existing session.` : AGENT_API_KEYS_COPY.revokeDescription(pendingRevoke.title))
          : ""}
        confirmLabel={local ? "Remove key" : AGENT_API_KEYS_COPY.revokeConfirmLabel}
        confirmVariant="destructive"
        loading={source.revokePending}
        onClose={() => setPendingRevoke(null)}
        onConfirm={handleConfirmRevoke}
      />
    </SettingsPageBody>
  );
}
