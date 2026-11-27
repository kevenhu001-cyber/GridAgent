import type { SessionEventEnvelope } from "@anyharness/sdk";
import type { DesktopPiBridge, PiModelSelection } from "../../../host/desktop-bridge";
import { PiSessionController } from "./session-controller";
import { PiEventAdapter } from "./event-adapter";
import { createEmptySessionRecord, getSessionRecord, patchSessionRecord, putSessionRecord } from "#product/stores/sessions/session-records";
import { useSessionIntentStore } from "#product/stores/sessions/session-intent-store";
import { useSessionIngestStore } from "#product/stores/sessions/session-ingest-store";
import { applyStreamEnvelopeBatch } from "#product/lib/domain/sessions/stream/stream-state";
import { buildSessionStreamBatchPatch } from "#product/lib/domain/sessions/stream-patch";
import { batchSessionStoreWrites } from "#product/lib/infra/scheduling/react-batching";
import type { PromptOutboxEntry } from "#product/domain/sessions/intents/session-intent-model";

export const PI_AGENT_KIND = "pi";
type Binding = { clientId: string; workspaceId: string; hostId: string;
  controller: PiSessionController; adapter: PiEventAdapter; selection: PiModelSelection; busy: boolean; failed: boolean };
let binding: Binding | null = null;
let opening = false;

// Transport ownership only. Transcript, directory, freshness and prompt outbox
// are the existing ProductClient stores, not a parallel conversation store.
export function isPiProductSession(sessionId: string): boolean {
  return getSessionRecord(sessionId)?.agentKind === PI_AGENT_KIND;
}

function applyNativeEvents(current: Binding, envelopes: SessionEventEnvelope[]) {
  if (!envelopes.length) return;
  const slot = getSessionRecord(current.clientId);
  if (!slot || slot.materializedSessionId !== current.hostId || slot.workspaceId !== current.workspaceId ||
      envelopes.some(e=>e.sessionId!==current.hostId)) throw new Error("Native session identity changed");
  const result = applyStreamEnvelopeBatch({events:slot.events,transcript:slot.transcript},envelopes);
  if (result.gapEnvelope) {
    useSessionIngestStore.getState().markStale(current.clientId,{gapAfterSeq:slot.transcript.lastSeq});
    throw new Error("Native event gap; do not replay");
  }
  const patch = buildSessionStreamBatchPatch({slot,nextTranscript:result.state.transcript,envelopes:result.appliedEnvelopes});
  batchSessionStoreWrites(()=>{
    patchSessionRecord(current.clientId,{...patch,events:result.state.events,
      transcriptHydrated:true,streamConnectionState:"open",
      optimisticPrompt:null});
    useSessionIntentStore.getState().reconcileFromEnvelopes(current.clientId,
      [...result.duplicateEnvelopes,...result.appliedEnvelopes],patch.transcript);
    useSessionIngestStore.getState().applyStreamProgress(current.clientId,{
      lastAppliedSeq:patch.transcript.lastSeq,lastObservedSeq:patch.transcript.lastSeq,gapAfterSeq:null,
    });
  });
}

function markInterrupted(current: Binding) {
  current.failed = true;
  try { applyNativeEvents(current,current.adapter.disconnect()); } catch { /* preserve the last trustworthy cursor */ }
  patchSessionRecord(current.clientId,{status:"errored",streamConnectionState:"disconnected",
    executionSummary:{phase:"errored",hasLiveHandle:false,pendingInteractions:[],updatedAt:new Date().toISOString()}});
  useSessionIngestStore.getState().markStale(current.clientId);
}

/** Explicitly admitted local workspace and model. No restored session may
 * open a new worker implicitly. Initial host supports one live session.
 * Called by the retained workspace composer workflow, not a new UI.
 */
export async function openPiProductSession(input:{bridge:DesktopPiBridge;workspaceId:string;workspacePath:string;selection:PiModelSelection}):Promise<string> {
  if (binding || opening) throw new Error("A native Pi session is already open");
  if (!input.workspaceId || !input.workspacePath) throw new Error("Missing workspace");
  opening = true;
  const controller = new PiSessionController(input.bridge);
  try {
    if (!await input.bridge.mode() || !await input.bridge.matchesWorkspace(input.workspacePath)) throw new Error("Workspace is not authorized for native Pi");
    await controller.open(input.workspacePath,input.selection);
    const hostId = controller.getSnapshot().sessionId;
    if (!hostId || getSessionRecord(hostId)) throw new Error("Native session identity collision");
    const record = createEmptySessionRecord(hostId,PI_AGENT_KIND,{workspaceId:input.workspaceId,
      materializedSessionId:hostId,modelId:input.selection.modelId,sessionRelationship:{kind:"root"}});
    putSessionRecord({...record,status:"idle",streamConnectionState:"open",transcriptHydrated:true});
    binding={clientId:hostId,workspaceId:input.workspaceId,hostId,controller,
      adapter:new PiEventAdapter(hostId),selection:{...input.selection},busy:false,failed:false};
    return hostId;
  } catch (error) {
    try {await controller.close();} catch { /* native admission uncertain; no retry */ }
    throw error;
  } finally {opening=false;}
}

function failIntent(entry:PromptOutboxEntry, uncertain:boolean,message:string) {
  const latest=useSessionIntentStore.getState().entriesById[entry.intentId];
  if (latest?.kind!=="send_prompt" || latest.deliveryState==="echoed_tombstone" || latest.deliveryState==="cancelled") return;
  useSessionIntentStore.getState().patchIntent(entry.intentId,{
    status:uncertain?"dispatching":"failed",deliveryState:uncertain?"unknown_after_dispatch":"failed_before_dispatch",errorMessage:message,
  });
}

/** Reuse the existing outbox entry and prompt ID; hold dispatch ownership until
 * settlement. Unsupported structured blocks are rejected, never flattened.
 */
export async function dispatchPiPromptIntent(entry:PromptOutboxEntry):Promise<void> {
  const store=useSessionIntentStore.getState();
  const latest=store.entriesById[entry.intentId];
  if (latest?.kind!=="send_prompt" || latest.deliveryState!=="waiting_for_session") return;
  const current=binding;
  if (!current || current.clientId!==entry.clientSessionId || current.hostId!==entry.materializedSessionId ||
    current.workspaceId!==entry.workspaceId || current.failed || current.busy || current.controller.getSnapshot().status!=="ready") {
    failIntent(entry,false,"Native Pi session is not available. Do not resume a restored session automatically."); return;
  }
  if (entry.attachmentSnapshots.length || entry.blocks.length!==1 || entry.blocks[0].type!=="text" ||
    !entry.blocks[0].text.trim() || new TextEncoder().encode(entry.blocks[0].text).length>8192) {
    failIntent(entry,false,"Native Pi currently accepts one text block of up to 8192 UTF-8 bytes.");return;
  }
  current.busy=true;
  store.patchIntent(entry.intentId,{status:"dispatching",deliveryState:"dispatching",dispatchedAt:new Date().toISOString()});
  let admitted=false;
  try {
    const requestId=await current.controller.prompt(entry.blocks[0].text);
    admitted=true;
    store.patchIntent(entry.intentId,{status:"accepted",deliveryState:"accepted_running",acceptedAt:new Date().toISOString(),placement:"transcript"});
    patchSessionRecord(current.clientId,{hasAttemptedPrompt:true,lastPromptAt:new Date().toISOString()});
    applyNativeEvents(current,current.adapter.begin(requestId,entry.clientPromptId,entry.blocks[0].text));
    const settled=await current.controller.drainTurn(events=>{
      // Preserve per-event application even if a later event in a batch is malformed.
      for (const event of events) applyNativeEvents(current,current.adapter.accept(event));
    });
    if (settled.status!=="ready" || getSessionRecord(current.clientId)?.status==="errored") markInterrupted(current);
  } catch {
    failIntent(entry,true,admitted?"Native event stream interrupted; inspect existing work.":"Native submission was not confirmed; do not replay.");
    markInterrupted(current);
  } finally {current.busy=false;}
}

export async function cancelPiProductSession(sessionId:string):Promise<void> {
  const current=binding;
  if (!current || current.clientId!==sessionId || current.failed) throw new Error("Native Pi session unavailable");
  const id=current.controller.getSnapshot().requestId;
  if (!id) throw new Error("No admitted Pi turn");
  current.adapter.noteCancellation(id);
  await current.controller.cancel();
}

export async function closePiProductSession(sessionId:string):Promise<void> {
  const current=binding;
  if (!current || current.clientId!==sessionId || current.busy) throw new Error("Native Pi session is not idle");
  if (Object.values(useSessionIntentStore.getState().entriesById).some(intent=>intent.clientSessionId===sessionId && intent.kind==="send_prompt" && ["waiting_for_session","preparing","dispatching","accepted_running","accepted_queued"].includes(intent.deliveryState))) throw new Error("Native Pi has a pending prompt");
  await current.controller.close();
  binding=null;
  patchSessionRecord(sessionId,{status:"closed",streamConnectionState:"ended",
    executionSummary:{phase:"closed",hasLiveHandle:false,pendingInteractions:[],updatedAt:new Date().toISOString()}});
}

// Nonsecret transport metadata; never store another transcript.
export function getPiSessionSelection(sessionId:string): PiModelSelection | null {
  return binding?.clientId===sessionId ? {...binding.selection} : null;
}
export function canSendPiSession(sessionId:string,workspaceId:string):boolean {
  return binding?.clientId===sessionId && binding.workspaceId===workspaceId && !binding.failed &&
    !!getSessionRecord(sessionId) && ["ready","sending","running","cancelling"].includes(binding.controller.getSnapshot().status);
}
export function hasOpenPiSession():boolean { return binding!==null || opening; }
export function ownsPiSession(sessionId:string):boolean {return binding?.clientId===sessionId;}
