import { afterEach, describe, expect, it, vi } from "vitest";
import type { DesktopPiBridge, PiEvent } from "../../../host/desktop-bridge";
import { openPiProductSession, dispatchPiPromptIntent, cancelPiProductSession, closePiProductSession } from "./product-session";
import { getSessionRecord, removeSessionRecord } from "#product/stores/sessions/session-records";
import { useSessionIntentStore } from "#product/stores/sessions/session-intent-store";
import { useSessionIngestStore } from "#product/stores/sessions/session-ingest-store";

const hostId="a".repeat(32), turnId="b".repeat(32);
let opened=false;
function fixture() {
  const events:PiEvent[]=[{kind:"ready",version:1}];
  const bridge:DesktopPiBridge={
    mode:vi.fn(async()=>true), matchesWorkspace:vi.fn(async()=>true),
    open:vi.fn(async()=>hostId), prompt:vi.fn(async()=>turnId),
    abort:vi.fn(async()=>{}), poll:vi.fn(async()=>events.splice(0)),
    close:vi.fn(async()=>{}),
  };
  return {bridge,events};
}
async function open(bridge:DesktopPiBridge) {
  const id=await openPiProductSession({bridge,workspaceId:"workspace",workspacePath:"/project",selection:{provider:"openai",modelId:"model"}});
  opened=true;
  return id;
}
function enqueue(id:string, text="calculate", workspaceId="workspace") {
  return useSessionIntentStore.getState().enqueuePrompt({clientPromptId:id,clientSessionId:hostId,materializedSessionId:hostId,
    workspaceId,text,blocks:[{type:"text",text}]});
}
afterEach(async()=>{
  if(opened){await closePiProductSession(hostId);opened=false;}
  removeSessionRecord(hostId);
  useSessionIntentStore.getState().clear();
  useSessionIngestStore.getState().clear();
});
describe("native Pi transport reuses original ProductClient stores",()=>{
  it("materializes a session, reconciles the prompt echo and streams text/tools into the existing transcript",async()=>{
    const {bridge,events}=fixture();
    expect(await open(bridge)).toBe(hostId);
    expect(bridge.open).toHaveBeenCalledWith("/project",{provider:"openai",modelId:"model"});
    const entry=enqueue("prompt-one");
    events.push({kind:"started",id:turnId},{kind:"text",id:turnId,delta:"result"},
      {kind:"tool_started",id:turnId,name:"read",tool_id:"tool"},
      {kind:"tool_finished",id:turnId,name:"read",tool_id:"tool",error:false},
      {kind:"settled",id:turnId});
    await dispatchPiPromptIntent(entry);
    const record=getSessionRecord(hostId)!;
    expect(record.agentKind).toBe("pi");
    expect(record.status).toBe("idle");
    expect(record.transcript.turnOrder).toEqual([turnId]);
    expect(Object.values(record.transcript.itemsById).map(item=>item.kind)).toEqual(["user_message","assistant_prose","tool_call"]);
    expect(Object.values(record.transcript.itemsById)[1]).toMatchObject({text:"result",isStreaming:false});
    expect(useSessionIntentStore.getState().entriesById[entry.intentId]).toMatchObject({deliveryState:"echoed_tombstone"});
    expect(useSessionIngestStore.getState().freshnessByClientSessionId[hostId].lastAppliedSeq).toBe(record.transcript.lastSeq);
    await dispatchPiPromptIntent(entry);
    expect(bridge.prompt).toHaveBeenCalledTimes(1);
  });
  it("rejects a foreign workspace before any native request",async()=>{
    const {bridge}=fixture(); await open(bridge);
    const entry=enqueue("foreign","calculate","another");
    await dispatchPiPromptIntent(entry);
    expect(bridge.prompt).not.toHaveBeenCalled();
    expect(useSessionIntentStore.getState().entriesById[entry.intentId]).toMatchObject({deliveryState:"failed_before_dispatch"});
  });
  it("does not replay an uncertain send",async()=>{
    const {bridge}=fixture();await open(bridge);
    vi.mocked(bridge.prompt).mockRejectedValueOnce(new Error("disconnected"));
    const entry=enqueue("uncertain");
    await dispatchPiPromptIntent(entry);
    await dispatchPiPromptIntent(entry);
    expect(bridge.prompt).toHaveBeenCalledTimes(1);
    expect(useSessionIntentStore.getState().entriesById[entry.intentId]).toMatchObject({deliveryState:"unknown_after_dispatch"});
    expect(getSessionRecord(hostId)?.status).toBe("errored");
  });
  it("records a cancellation request without claiming that scientific jobs stopped",async()=>{
    const {bridge,events}=fixture();await open(bridge);
    const entry=enqueue("cancel");
    const running=dispatchPiPromptIntent(entry);
    await vi.waitFor(()=>expect(getSessionRecord(hostId)?.status).toBe("running"));
    await cancelPiProductSession(hostId);
    expect(bridge.abort).toHaveBeenCalledWith(hostId,turnId);
    events.push({kind:"settled",id:turnId});
    await running;
    const record=getSessionRecord(hostId)!;
    expect(record.status).toBe("errored");
    expect(record.events.some(e=>e.event.type==="turn_ended")).toBe(false);
    expect(record.events.some(e=>e.event.type==="error" && e.event.code==="PI_OUTCOME_UNCONFIRMED")).toBe(true);
  });
});
